# Algorithms & Math Learning Guide (English + தமிழ்)

> **Who is this for? / இது யாருக்கானது?**
> **EN:** A beginner-friendly, step-by-step guide to every algorithm and mathematical formula used in the **Bricks** IMU gesture engine — from raw Bluetooth bytes to 3D quaternions and Machine Learning.
> **தமிழ்:** **Bricks** சென்சார் சைகை (gesture) அமைப்பில் பயன்படுத்தப்படும் அனைத்து அல்காரிதம்களும் கணிதச் சூத்திரங்களும் — Bluetooth தரவு முதல் 3D குவாட்டர்னியன் (Quaternion) மற்றும் இயந்திர கற்றல் (ML) வரை — ஆரம்பநிலையாளர்களுக்கும் எளிதில் புரியும் வகையில் இங்கே விளக்கப்பட்டுள்ளன.

**Related Roadmap / தொடர்புடைய வழிகாட்டி:** [v1.0-raodmap.md](v1.0-raodmap.md)

---

## Contents / உள்ளடக்கம்
1. [Raw Sensor Math & Binary Decoding / சென்சார் தரவு & பைனரி விளக்கம்](#1-raw-sensor-math--binary-decoding--சென்சார்-தரவு--பைனரி-விளக்கம்)
2. [Smoothing Filters (EMA & Butterworth) / வடிகட்டுதல் (EMA & Butterworth)](#2-smoothing-filters-ema--butterworth--வடிகட்டுதல்-ema--butterworth)
3. [Calibration & Coordinate Alignment / அளவீடு & அச்சு சீரமைப்பு](#3-calibration--coordinate-alignment--அளவீடு--அச்சு-சீரமைப்பு)
4. [Dead-Zone, Hysteresis & Velocity Mapping / வரம்புகள் & வேக மாற்றம்](#4-dead-zone-hysteresis--velocity-mapping--வரம்புகள்--வேக-மாற்றம்)
5. [Flick, Slice & Hold/Dwell Detectors / சைகை கண்டறிதல் அல்காரிதம்கள்](#5-flick-slice--holddwell-detectors--சைகை-கண்டறிதல்-அல்காரிதம்கள்)
6. [3D Orientation, Quaternions & Madgwick Fusion / 3D திசை & சென்சார் இணைப்பு](#6-3d-orientation-quaternions--madgwick-fusion--3d-திசை--சென்சார்-இணைப்பு)
7. [Machine Learning & Signal Features / இயந்திர கற்றல் & சிக்னல் அம்சங்கள்](#7-machine-learning--signal-features--இயந்திர-கற்றல்--சிக்னல்-அம்சங்கள்)
8. [Formula Cheat Sheet / சூத்திர சுருக்கம்](#8-formula-cheat-sheet--சூத்திர-சுருக்கம்)

---

## 1. Raw Sensor Math & Binary Decoding / சென்சார் தரவு & பைனரி விளக்கம்

### 1.1 Scaling 16-bit Sensor Integers (`int16` → `g` and `°/s`)
- **English:** Over Bluetooth (BLE), the sensor sends raw 16-bit signed integers from `-32768` to `+32767` (2 bytes per axis, little-endian `"<hhh"`). To convert a raw integer into real physical units, multiply by `(full_range / 32768.0)`.
- **தமிழ்:** Bluetooth (BLE) வழியாக சென்சார் `-32768` முதல் `+32767` வரையிலான 16-பிட் முழு எண்களை (integers) அனுப்புகிறது. இதை உண்மையான இயற்பியல் அளவாக (`g` அல்லது `°/s`) மாற்ற, `(அதிகபட்ச அளவு / 32768.0)` என்பதால் பெருக்க வேண்டும்.

$$
a_x = x_{\text{raw}} \times \frac{4.0}{32768.0} \text{ (in g)}, \qquad g_x = gx_{\text{raw}} \times \frac{500.0}{32768.0} \text{ (in °/s)}
$$

- **Worked Example / உதாரணம்:**
  If raw `az = 8192`, then `8192 × (4.0 / 32768.0) = 1.0 g` (normal gravity pointing straight down / சாதாரண புவியீர்ப்பு விசை).
- **Code / குறியீடு:** [`_parse_acc`](file:///Users/jerold/dev/Bricks/shared/sensor.py#L846), [`_parse_gyro`](file:///Users/jerold/dev/Bricks/shared/sensor.py#L858), scales at [`sensor.py#L188-L190`](file:///Users/jerold/dev/Bricks/shared/sensor.py#L188-L190).

### 1.2 Vector Magnitude (Total Strength / மொத்த அளவு)
- **English:** We often want to know *how fast* the hand is moving overall, regardless of direction (x, y, or z). Using the 3D Pythagorean theorem:
- **தமிழ்:** எந்தத் திசை (x, y, z) என்பதைப் பார்க்காமல், கை **மொத்தமாக எவ்வளவு வேகமாக** நகர்கிறது என்பதை அறிய 3D பிதாகரஸ் சூத்திரத்தைப் பயன்படுத்துகிறோம்:

$$
\|\mathbf{v}\| = \sqrt{v_x^2 + v_y^2 + v_z^2}
$$

- **Worked Example / உதாரணம்:** If `gx = 60`, `gy = 80`, `gz = 0 °/s`, then `av_mag = √(60² + 80² + 0²) = √10000 = 100 °/s`.
- **Code / குறியீடு:** `av_mag` in [`SliceDetector.update`](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py#L79) and `gyro_mag` in [`GestureInterpreter._process`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L434).

---

## 2. Smoothing Filters (EMA & Butterworth) / வடிகட்டுதல் (EMA & Butterworth)

### 2.1 Exponential Moving Average (EMA) — Low-Pass Filter
- **English:**
  - **Problem:** Raw accelerometer data mixes slow gravity (what we need for tilt) with fast hand shakes/vibrations (noise).
  - **Idea:** Blend a tiny fraction ($\alpha = 0.05$) of the *new* sample with $95\%$ of the *previous* smoothed value. Sudden spikes get ignored; slow tilts pass through.
- **தமிழ்:**
  - **பிரச்சனை:** Accelerometer தரவில் மெதுவான புவியீர்ப்பு விசையும் (tilt அறியத் தேவை) வேகமான கை அதிர்வுகளும் (noise) கலந்திருக்கும்.
  - **தீர்வு:** புதிய அளவின் $5\%$ ($\alpha = 0.05$) மற்றும் பழைய மதிப்பின் $95\%$ ஆகியவற்றைச் சேர்க்கிறோம். இதனால் திடீர் அதிர்வுகள் குறைந்து மெதுவான சாய்வு (tilt) மட்டும் கிடைக்கும்.

$$
y_n = \alpha\, x_n + (1 - \alpha)\, y_{n-1}
$$

- **Cutoff Frequency / வெட்டு அதிர்வெண்:**

$$
\tau = \frac{\Delta t (1 - \alpha)}{\alpha}, \qquad f_c = \frac{1}{2\pi \tau}
$$

  At $100\text{ Hz}$ ($\Delta t = 0.01\text{ s}$) and $\alpha = 0.05$: $\tau = 0.19\text{ s}$, $f_c \approx 0.84\text{ Hz}$ (slow response — lags ~0.2 s).
- **Code / குறியீடு:** [`gesture.py#L398-L401`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L398-L401).

### 2.2 2nd-Order Butterworth Filter (Biquad) — Planned Upgrade
- **English:**
  - **Why better than EMA?** EMA cuts off gradually and lags intentional movement. A **2nd-order Butterworth** filter lets frequencies below $f_c$ (e.g., `3 Hz` voluntary motion) pass flatly and drops higher frequencies (e.g., `4–12 Hz` tremor) sharply.
  - It uses the last 2 inputs and last 2 outputs:
- **தமிழ்:**
  - **ஏன் EMA-வை விட சிறந்தது?** EMA மெதுவான அசைவையும் கொஞ்சம் தாமதப்படுத்தும். **Butterworth** வடிகட்டி `3 Hz`-க்குக் குறைவான விருப்ப அசைவுகளைத் தாமதமின்றி அனுமதித்து, `4–12 Hz` நடுக்கத்தை (tremor) வேகமாக நீக்கும்.

$$
y_n = b_0 x_n + b_1 x_{n-1} + b_2 x_{n-2} - a_1 y_{n-1} - a_2 y_{n-2}
$$

```python
# Compute b, a once using scipy.signal.butter(2, fc=3.0, fs=fs)
y = b0*x + b1*x1 + b2*x2 - a1*y1 - a2*y2
x2, x1, y2, y1 = x1, x, y1, y
```

---

## 3. Calibration & Coordinate Alignment / அளவீடு & அச்சு சீரமைப்பு

### 3.1 Median Calibration (Neutral Posture / நடுநிலை அளவீடு)
- **English:** Collect 100 samples (~1 s) at rest, sort them, and pick the **middle value (median)** instead of the average (mean). Why? One big tremor spike ruins a mean, but does not move the median!
- **தமிழ்:** ஓய்வாக இருக்கும்போது 100 அளவுகளைச் சேகரித்து, அவற்றை வரிசைப்படுத்தி **நடு மதிப்பை (Median)** எடுக்கிறோம். ஏன் சராசரி (Mean) இல்லை? திடீர் நடுக்கம் (spike) சராசரியை மாற்றிவிடும், ஆனால் நடு மதிப்பை மாற்றாது!
  - Example / உதாரணம்: `[1.0, 1.0, 1.02, 0.99, 4.8]` → Mean = `1.76` (wrong!), **Median = `1.02`** (clean!).
- **Code / குறியீடு:** [`gesture.py#L408-L430`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L408-L430).

### 3.2 Adaptive Baseline / Washout Filter (தொடர் நடுநிலை மாற்றம்)
- **English:** If a child gets tired and their resting posture shifts slowly, we gently drag the neutral point toward the new resting posture *only when the gyro shows they are still* ($\|\omega\| < 45\text{ °/s}$).
- **தமிழ்:** விளையாடும்போது சோர்வால் குழந்தையின் ஓய்வு நிலை மெதுவாக மாறினால், கை அசையாமல் இருக்கும்போது ($\|\omega\| < 45\text{ °/s}$) மட்டும் நடுநிலையை மெதுவாகப் புதிய நிலைக்கு நகர்த்துகிறோம்.

$$
\text{if } \|\omega\| < 45: \quad \text{cal} \leftarrow ar \cdot \text{smooth} + (1 - ar) \cdot \text{cal} \quad (ar = 0.002)
$$

- **Important CP rule / முக்கிய விதி:** Pause this update while holding a gesture (`ARMING`), or the game will "forget" the child is holding the tilt!
- **Code / குறியீடு:** [`gesture.py#L431-L440`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L431-L440).

### 3.3 PCA Functional Axis Alignment (இயற்கை அசைவு திசை கண்டறிதல்)
- **English:**
  - **Problem:** Due to strap twist or arm contracture, a child's natural "left-right" swing might actually move diagonally on the sensor's $(x, y)$ axes.
  - **Idea:** Record 2.5 s of natural swings, compute the 2D covariance (how $x$ and $y$ spread together), and find the angle $\theta$ of the **longest spread** (1st Principal Component). Then rotate every future reading by $-\theta$.
- **தமிழ்:**
  - **பிரச்சனை:** சென்சார் சுற்றிக் கட்டப்பட்டிருந்தாலோ அல்லது கை சாய்வாக அசைந்தாலோ, குழந்தையின் இயல்பான இடது-வலது அசைவு சென்சாரில் மூலைவிட்டமாகத் (diagonal) தெரியும்.
  - **தீர்வு:** 2.5 வினாடிகள் இயல்பான அசைவைப் பதிவு செய்து, தரவு அதிகம் பரவியுள்ள கோணத்தை ($\theta$) **PCA** மூலம் கண்டுபிடித்து, அச்சுகளை அந்தக் கோணத்தில் சுழற்றுகிறோம்.

$$
c_{xx}=\sum (x-\bar x)^2,\quad c_{yy}=\sum (y-\bar y)^2,\quad c_{xy}=\sum (x-\bar x)(y-\bar y)
$$

$$
\theta = \tfrac{1}{2}\operatorname{atan2}(2c_{xy},\; c_{xx}-c_{yy})
$$

$$
x' = x\cos\theta + y\sin\theta, \qquad y' = -x\sin\theta + y\cos\theta
$$

- **Code / குறியீடு:** [`align_functional_axis`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L330-L353), applied at [`L464-L468`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L464-L468).

### 3.4 90th-Percentile Asymmetric ROM (வரம்பு அளவீடு — Planned)
- **English:** Instead of `max(tilt)` (which one spasm can inflate), use the **90th percentile** separately for Left and Right (and Up/Down) so asymmetric range of motion maps cleanly to full speed `[-1, +1]`.
- **தமிழ்:** அதிகபட்ச மதிப்பை (`max`) எடுத்தால் ஒரு திடீர் இழுப்பு (spasm) அளவைக் கெடுத்துவிடும். எனவே **90th percentile** மதிப்பை இடது மற்றும் வலது பக்கங்களுக்குத் தனித்தனியாக எடுத்து, `-1` முதல் `+1` வரை அளவிடுகிறோம்.

---

## 4. Dead-Zone, Hysteresis & Velocity Mapping / வரம்புகள் & வேக மாற்றம்

### 4.1 Dead-Zone + Linear Mapping (சாய்வு → வேகம்)
- **English:** Small wobbles inside `thr` become `0.0`. Beyond `thr`, speed scales smoothly up to `1.0` at `t_max`:
- **தமிழ்:** `thr` அளவுக்குக் குறைவான சிறிய அசைவுகள் `0.0` ஆக்கப்படும். அதற்கு மேல் `t_max` வரை வேகம் நேர்கோட்டில் `1.0` ஆக உயரும்:

$$
v = \operatorname{sign}(t)\cdot \min\!\left(1,\; \frac{|t| - thr}{t_{max} - thr}\right) \quad \text{if } |t| \ge thr,\; \text{else } 0
$$

- **Example / உதாரணம்:** If `thr = 0.05`, `t_max = 0.50`, and `t = 0.275`: `(0.275 - 0.05) / (0.50 - 0.05) = 0.50` (half speed / அரை வேகம்).
- **Code / குறியீடு:** [`gesture.py#L470-L488`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L470-L488) and spin at [`L540-L546`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L540-L546).

### 4.2 Hysteresis / Schmitt Trigger (துடிப்புத் தடுப்பு — Planned)
- **English:** One threshold causes flickering (`ON-OFF-ON`) if a tremor sits near the boundary. **Hysteresis** uses two thresholds: turn **ON** above `T_ON` (e.g. `0.25`), turn **OFF** only below `T_OFF` (e.g. `0.15`).
- **தமிழ்:** ஒரே ஒரு வரம்பு இருந்தால் நடுக்கத்தால் மதிப்பு `ON-OFF-ON` எனத் துடிக்கும். **Hysteresis** இரண்டு வரம்புகளைப் பயன்படுத்தும்: `T_ON` (`0.25`) தாண்டினால் **ON**, `T_OFF` (`0.15`)-க்குக் கீழ் வந்தால் மட்டுமே **OFF**.

```python
if not active and abs(x) > T_ON:  active = True
elif active and abs(x) < T_OFF:   active = False
```

---

## 5. Flick, Slice & Hold/Dwell Detectors / சைகை கண்டறிதல் அல்காரிதம்கள்

### 5.1 Sliding-Window Peak + Cooldown (Flick / Launch)
- **English:** Keep the last $N$ samples in a `deque(maxlen=N)`. If the peak exceeds `flick_threshold` AND enough cooldown time has passed since the last trigger, fire once.
- **தமிழ்:** கடைசி $N$ அளவுகளை ஒரு `deque`-ல் வைத்து, அதில் அதிகபட்ச மதிப்பு வரம்பைத் தாண்டி, குறிப்பிட்ட ஓய்வு நேரம் (cooldown) முடிந்திருந்தால் சைகையை இயக்குகிறோம்.
- **Code / குறியீடு:** [`gesture.py#L492-L533`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L492-L533). *(Note: Fix `abs()` so downward spasms don't trigger upward `launch`!)*

### 5.2 Slice Direction Classification & Combo Counter
- **English:** [`SliceDetector`](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py#L42) stores 8 frames (~80 ms). When peak `av_mag >= 150 °/s` (after `0.25 s` cooldown), it averages `mean_gz` (left/right) and `mean_gy` (up/down) and compares them with a **1.5× axis-dominance ratio**:
  - `|mean_gz| > 1.5 × |mean_gy|` → `"right"` or `"left"`
  - `|mean_gy| > 1.5 × |mean_gz|` → `"up"` or `"down"`
  - Otherwise → `"diagonal_*"`
  - **Combo:** keeps slice timestamps in a queue and drops any older than `1.5 s`.
- **தமிழ்:** 8 ஃப்ரேம்களில் சுழற்சி வேகம் `150 °/s`-ஐத் தாண்டினால், `mean_gz` மற்றும் `mean_gy` மதிப்புகளை **1.5× விகிதத்துடன்** ஒப்பிட்டு இடது/வலது/மேல்/கீழ் அல்லது மூலைவிட்டத் திசையைக் கணக்கிடுகிறது. கடந்த `1.5 s`-க்குள் நடந்த வெட்டுகளின் எண்ணிக்கையே combo.
- **Code / குறியீடு:** [`_classify_direction`](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py#L127-L160), [`combo_count`](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py#L162-L176).

### 5.3 Hold / Dwell State Machine (CP-Safe Button — Planned)
- **English:** A brief involuntary spasm cannot stay tilted for `0.5 s`. A **3-state machine** (`IDLE → ARMING → FIRED`) only fires after the child holds past `T_ON` for `hold_time` seconds, and requires returning below `T_OFF` before firing again.
- **தமிழ்:** திடீர் நடுக்கம் (spasm) `0.5 s` தொடர்ந்து நிற்காது. எனவே குழந்தை `T_ON` அளவைத் தாண்டி `hold_time` நேரம் **பிடித்து வைத்திருந்தால்** மட்டுமே (`IDLE → ARMING → FIRED`) இயங்கும்; மீண்டும் இயக்க `T_OFF`-க்குக் கீழ் வர வேண்டும்.

### 5.4 Jerk & Duration Spasm Gate (திடீர் இழுப்புத் தடுப்பு — Planned)
- **English:** **Jerk** is how fast acceleration changes: $\text{jerk} = |a_n - a_{n-1}| / \Delta t$. Sudden involuntary bursts have huge jerk and short duration (`< 150 ms`), so the gate blocks discrete triggers from those windows.
- **தமிழ்:** **Jerk** என்பது முடுக்கம் எவ்வளவு திடீரென மாறுகிறது என்பதாகும் ($\Delta a / \Delta t$). திடீர் இழுப்புகளில் Jerk மிக அதிகமாகவும் நேரம் மிகக் குறைவாகவும் (`< 150 ms`) இருக்கும்; அவற்றை இது தடுக்கும்.

---

## 6. 3D Orientation, Quaternions & Madgwick Fusion / 3D திசை & சென்சார் இணைப்பு

### 6.1 What is a Quaternion? (`q = (w, x, y, z)`)
- **English:** Euler angles (`roll, pitch, yaw`) suffer from **gimbal lock** (axes align at ±90° pitch) and sudden jumps from `+180°` to `-180°`. A **unit quaternion** uses 4 numbers (`w²+x²+y²+z² = 1`) to represent any 3D orientation smoothly with zero jumps.
- **தமிழ்:** Euler கோணங்களில் (`roll, pitch, yaw`) ±90°-ல் **Gimbal lock** மற்றும் ±180°-ல் திடீர் தாவல் ஏற்படும். **குவாட்டர்னியன் (Quaternion)** `(w, x, y, z)` என்ற 4 எண்கள் மூலம் எந்த 3D கோணத்தையும் தடையின்றி மென்மையாகக் குறிக்கிறது.

### 6.2 Madgwick 6-DOF Sensor Fusion (Software Fallback)
- **English:** Hardware Bosch `IMUPlus` mode computes quaternions on the sensor chip. When raw mode fallback is used, [`MadgwickFilter`](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py#L36) fuses gyro + accel in 3 steps per sample:
  1. **Gyro prediction (fast, drifts):** $\dot{q}_\omega = \tfrac{1}{2}\, q \otimes (0, \omega_x, \omega_y, \omega_z)$
  2. **Gravity error (slow, drift-free):** Compare rotated `[0, 0, 1]` with normalised measured accel `(ax_n, ay_n, az_n)` to get error $f(q)$ and gradient $\nabla f = J^T f$.
  3. **Gradient-descent blend & normalise** ($\beta = 0.033$):
- **தமிழ்:** சென்சாரில் உள்ள Bosch சிப் நேரடியாக Quaternion தரும். Raw முறையில் மட்டும் [`MadgwickFilter`](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py#L36) கைரோஸ்கோப் வேகத்தையும் புவியீர்ப்புத் திசையையும் **Gradient Descent** மூலம் இணைக்கிறது:

$$
q \leftarrow q + \left(\dot{q}_\omega - \beta \frac{\nabla f}{\|\nabla f\|}\right)\Delta t, \qquad q \leftarrow \frac{q}{\|q\|}
$$

- **Code / குறியீடு:** [`MadgwickFilter.update`](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py#L55-L157).

### 6.3 Removing Gravity → Linear Acceleration (`lin_acc`)
- **English:** Rotate the world gravity vector `[0, 0, 1] g` into the sensor's tilted frame using $q$, then subtract it from `(ax, ay, az)`. What remains is **pure hand movement acceleration**.
- **தமிழ்:** உலக புவியீர்ப்புத் திசையை (`[0, 0, 1] g`) சென்சாரின் சாய்வுக்கு ஏற்ப சுழற்றி, அளந்த `(ax, ay, az)`-லிருந்து கழித்தால், **கை நகர்வின் உண்மையான முடுக்கம் (Linear Acceleration)** மட்டும் கிடைக்கும்.
- **Code / குறியீடு:** [`get_linear_accel`](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py#L198-L222).

### 6.4 Baseline Quaternion Normalization ($q_{\text{rel}} = q_{\text{base}}^{-1} \otimes q$) — Planned
- **English:** Save the resting quaternion $q_{\text{base}}$ during calibration. For any live orientation $q$, multiply by the **inverse (conjugate)** $q_{\text{base}}^{-1} = (w_0, -x_0, -y_0, -z_0)$. Then `q_rel` equals identity `(1, 0, 0, 0)` at rest, no matter how the sensor was strapped on! Finally convert `q_rel` to `(roll, pitch)` for games or the **Orientation Pointer**:
- **தமிழ்:** ஓய்வு நிலையில் $q_{\text{base}}$ ஐ சேமித்து, ஒவ்வொரு புதிய $q$-வையும் அதன் தலைகீழ் மதிப்பால் ($q_{\text{base}}^{-1}$) பெருக்கினால், சென்சார் எந்தக் கோணத்தில் கட்டப்பட்டிருந்தாலும் ஓய்வு நிலை `(1, 0, 0, 0)` ஆக மாறும். பிறகு அதிலிருந்து `(roll, pitch)` எடுத்து திரைச் சுட்டிக்குப் (Pointer) பயன்படுத்தலாம்:

$$
x_{px} = \tfrac{W}{2}\,(1 + \text{tilt}_x), \qquad y_{px} = \tfrac{H}{2}\,(1 - \text{tilt}_y)
$$

- **Quaternion → Euler code / குறியீடு:** [`get_euler_deg`](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py#L163-L196).

---

## 7. Machine Learning & Signal Features / இயந்திர கற்றல் & சிக்னல் அம்சங்கள்

### 7.1 Sliding Window & 38 Summary Features
- **English:** An ML tree cannot easily read 36 raw frames × 8 numbers directly. Instead, [`FeatureExtractor`](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py#L151) converts each 36-frame window (centred on the motion peak) into **38 summary numbers**:
- **தமிழ்:** 36 ஃப்ரேம்களின் மூல எண்களை நேரடியாகப் படிப்பதற்குப் பதிலாக, [`FeatureExtractor`](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py#L151) அந்தச் சாளரத்தை (window) **38 சுருக்க எண்களாக (features)** மாற்றுகிறது:

| Feature / அம்சம் | Formula / கணக்கீடு | What it tells the model / பயன் |
|---|---|---|
| **Mean, Std, Max-Abs** | $\bar x,\; \sqrt{\frac{1}{N}\sum(x_i-\bar x)^2},\; \max|x_i|$ | Average direction, spread, peak strength / திசை மற்றும் வலிமை |
| **RMS (Energy)** | $\sqrt{\frac{1}{N}\sum (x_i^2+y_i^2+z_i^2)}$ | Total motion energy / மொத்த அசைவு ஆற்றல் |
| **Jerk** | $\frac{1}{N-1}\sum |x_i - x_{i-1}|$ | Sharpness (spasms have high jerk) / திடீர் வேக மாற்றம் |
| **Zero Crossings** | Count of $x_{i-1}\cdot x_i < 0$ | Back-and-forth oscillation vs one-way move / முன்னும் பின்னும் அசைவு |
| **Peak Timing** | $\text{peak\_idx} / (N - 1)$ | Where the peak happens in `[0..1]` / உச்சம் நிகழும் இடம் |
| **Signed Area** | $\sum x_i$ | Net directional push (left vs right) / நிகர திசை |
| **Dominant Angle** | $\operatorname{atan2}(\overline{gy}, \overline{gz})$ | 2D sweep angle / சுழற்சி கோணம் |

### 7.2 Frequency Features (FFT & Spectral Entropy) — Planned for CP
- **English:** Research shows **dyskinesia (0–4 Hz)** overlaps **voluntary movement (0.3–2 Hz)**, while **tremor is 4–12 Hz**. Using **FFT** (Fast Fourier Transform), we split a window into frequencies and compute:
  1. **Low-band energy ratio** (`0.3–2 Hz` power ÷ total power): higher for smooth voluntary gestures.
  2. **Spectral entropy:** measures how spread-out/chaotic the frequencies are (low = clean gesture, high = noisy spasm).
- **தமிழ்:** ஆய்வின்படி விருப்ப அசைவு (`0.3–2 Hz`) மற்றும் டிஸ்கினீசியா (`0–4 Hz`) அதிர்வெண்கள் ஒன்றோடொன்று கலக்கின்றன; நடுக்கம் `4–12 Hz`-ல் இருக்கும். **FFT** மூலம்:
  1. **குறைந்த அதிர்வெண் ஆற்றல் விகிதம் (`0.3–2 Hz`)**: மென்மையான விருப்ப அசைவில் அதிகம்.
  2. **Spectral Entropy**: அதிர்வெண்களின் ஒழுங்கற்ற தன்மையை அளவிடும் (குறைவு = தெளிவான சைகை; அதிகம் = ஒழுங்கற்ற இழுப்பு).

$$
H = -\frac{\sum_k p_k \ln(p_k)}{\ln K}, \qquad p_k = \frac{P_k}{\sum_j P_j}
$$

### 7.3 RandomForest, Confidence Abstain & Two-Stage CP Design
- **English:**
  - **Decision Tree:** Learns yes/no splits on features (e.g., `mean_gz > 40?` → `jerk < 15?`).
  - **RandomForest:** Combines **60 trees** (`max_depth=8`), each trained on a random sample of the data and random features. All 60 trees vote; the vote share is **confidence** (`predict_proba`).
  - **Abstain:** If `confidence < threshold` (e.g. `0.55`), output `None` — better to miss one gesture than fire a wrong move!
  - **Temporal Smoothing:** Majority vote over the last 4–6 frames removes single-frame flicker.
  - **Two-Stage Upgrade for CP:**
    - *Stage 1:* RandomForest classifies **`rest` vs `intentional` vs `involuntary`** (so spasms are never forced into `"left"`/`"right"`).
    - *Stage 2:* Only if Stage 1 predicts `intentional`, classify which gesture (RandomForest, or **DTW — Dynamic Time Warping** if the child only recorded 3–5 examples of a custom shape).
  - **Session-Aware Stratified k-Fold CV:** Keeps each recording session whole inside one fold so testing happens on unseen sessions, not leaked nearby frames.
- **தமிழ்:**
  - **RandomForest:** **60 முடிவு மரங்கள் (Decision Trees)** தனித்தனித் தரவுத் துண்டுகளில் பயிற்சி பெற்று வாக்களிக்கும். அதிக மரங்கள் ஒப்புக்கொண்டால் **நம்பிக்கை (Confidence)** அதிகம்.
  - **Abstain (தவிர்த்தல்):** நம்பிக்கை வரம்பை விடக் குறைவாக இருந்தால் எதுவும் இயக்காது (தவறான சைகையை விட இயக்காமல் இருப்பது பாதுகாப்பானது).
  - **இரண்டு-நிலை அமைப்பு (Two-Stage for CP):** *நிலை 1* `rest / intentional / involuntary` எனப் பிரித்து திடீர் இழுப்புகளைத் தடுக்கும்; *நிலை 2* மட்டுமே குறிப்பிட்ட சைகையை அடையாளம் காணும்.
- **Code / குறியீடு:** [`GestureModel`](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py#L484), [`GestureValidator`](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py#L594).

---

## 8. Formula Cheat Sheet / சூத்திர சுருக்கம்

| Concept / கருத்து | Formula / சூத்திரம் | Where / எங்கே |
|---|---|---|
| Scale int16 accel | $a = x_{\text{raw}} \cdot \frac{4.0}{32768}$ | [`sensor.py#L188`](file:///Users/jerold/dev/Bricks/shared/sensor.py#L188) |
| 3D Magnitude | $\|\mathbf{v}\| = \sqrt{v_x^2 + v_y^2 + v_z^2}$ | [`gesture_detector.py#L79`](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py#L79) |
| EMA Low-Pass | $y_n = \alpha x_n + (1-\alpha) y_{n-1}$ | [`gesture.py#L398`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L398) |
| Biquad (Butterworth) | $y_n = b_0 x_n + b_1 x_{n-1} + b_2 x_{n-2} - a_1 y_{n-1} - a_2 y_{n-2}$ | Planned §7.2 |
| Dead-zone Mapping | $v = \operatorname{sign}(t)\min(1, \frac{|t|-thr}{t_{max}-thr})$ | [`gesture.py#L477`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L477) |
| PCA Axis Angle | $\theta = \frac{1}{2}\operatorname{atan2}(2c_{xy}, c_{xx}-c_{yy})$ | [`gesture.py#L350`](file:///Users/jerold/dev/Bricks/shared/gesture.py#L350) |
| Quaternion Relative | $q_{\text{rel}} = q_{\text{base}}^{-1} \otimes q$ | Planned §7.1 |
| Madgwick Update | $q \leftarrow q + (\dot{q}_\omega - \beta\frac{\nabla f}{\|\nabla f\|})\Delta t$ | [`fusion_processor.py#L136`](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py#L136) |
| Mean Jerk | $\frac{1}{N-1}\sum |x_i - x_{i-1}|$ | [`gesture_learner.py#L216`](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py#L216) |
| Spectral Entropy | $H = -\sum p_k \ln(p_k) / \ln K$ | Planned §7.7 |

