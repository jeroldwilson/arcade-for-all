# Version 0.5: DTW-Based Robust Gesture Learning Plan

This document provides a comprehensive explanation of the proposed Dynamic Time Warping (DTW) based gesture recognition algorithm (adapted from the paper "Orientation Independent Activity/Gesture Recognition Using Wearable Motion Sensors") and a detailed implementation plan to integrate it into the Arcade for All game.

---

## Part 1: Algorithm Explanation for Key Stakeholders

### For the Parent: What this means for your child
Right now, the game looks for a specific "shape" of movement in a very rigid way. If your child's watch is rotated slightly, if they wave too slowly, or if their arm drops heavily at the end, the game gets confused. 

This new algorithm introduces three superpowers:
1. **"Any-Angle" Sensing:** The game will calculate the *total amount of rotation* in 3D space, rather than caring which specific direction the watch is facing. If the assistant puts the watch on upside down, or the child rests their arm at a different angle, the game will still recognize the "Ta Ta" wave perfectly.
2. **Elastic Time (DTW):** Instead of giving the child exactly 0.6 seconds to complete a wave, the algorithm uses "Dynamic Time Warping." This is like a rubber band for time. It can stretch to match a slow, feeble wave, or compress to match a fast, aggressive spasm-wave. Both are recognized as the same intended action.
3. **Ignoring the Messy Parts:** The algorithm learns which parts of the wave are "intentional" (the core wave) and which parts are just "noise" (the jerky lift at the start, or the arm dropping at the end). It automatically masks out the noise, so your child is only judged on their actual intended gesture.

### For the Medical Device Coder: Robustness & Safety
From a clinical and assistive device perspective, the current heuristic of grabbing a 36-frame window centered on an arbitrary gyro peak is fragile. It's highly susceptible to motion artifacts (spasms, wheelchair bumps, or an assistant moving the arm).
- **False-Positive Rejection:** The new algorithm introduces a Maximum-Margin Hyperplane (MMH) thresholding technique. A gesture is only triggered if the entire continuous trajectory strictly matches the intentional template curve. Passive repositioning by an assistant will be mathematically rejected.
- **Inconsistent Segment Masking:** By using hierarchical clustering across training samples, the system identifies segments of high intra-class variance (e.g., fatigue drops) and applies "star-padding" to nullify their distance penalty during inference. This ensures high specificity without penalizing atypical motor termination phases.

### For the Beginner ML Engineer: Algorithm Deep-Dive & Mathematical Formulas
We are shifting paradigms from **Statistical Feature Engineering + Random Forest (Current Algorithm)** to **Time-Series Template Matching with Dynamic Time Warping (New Algorithm)**. 

#### Variation Between Current vs. New Algorithm
*   **Current Algorithm (Random Forest):** 
    *   *Features:* Takes a fixed 36-frame window and calculates 38 statistical features (mean, std, max, RMS, jerk, zero-crossings) across the X, Y, and Z axes.
    *   *Weakness:* It is highly sensitive to the duration (speed) of the gesture and the physical orientation of the device (if X and Y swap, the model breaks). It also treats all parts of the 36-frame window equally, even noisy starts/stops.
*   **New Algorithm (DTW + Template Refinement):** 
    *   *Features:* Converts the 3-axis angular velocity into a single 1-Dimensional time-series curve representing cumulative rotation.
    *   *Strength:* Naturally handles gestures of varying speeds (by warping time), completely ignores sensor orientation, and actively masks out noisy segments of the gesture using Star-Padding.

#### 1. Feature Extraction: Total Angle Change Series
Instead of using raw angular velocities ($\omega_x, \omega_y, \omega_z$), we calculate the cumulative 3D rotation magnitude at every time step $i$.
*   **Mathematical Formula:** 
    $$\Delta \theta_i = \sqrt{\left(\sum_{j=1}^{i} \omega_{jx} \Delta t\right)^2 + \left(\sum_{j=1}^{i} \omega_{jy} \Delta t\right)^2 + \left(\sum_{j=1}^{i} \omega_{jz} \Delta t\right)^2}$$
    *Where $\Delta t$ is the reciprocal of the sampling frequency (e.g., $1/60$ seconds).*
*   **Why it matters:** This collapses 3 dimensions into 1 orientation-independent sequence. The "shape" of $\Delta \theta$ over time represents the gesture.

#### 2. Sequence Alignment: Dynamic Time Warping (DTW)
To compare an incoming stream of sensor data ($R$) against a saved "perfect gesture" template ($T$), we use the **Dynamic Time Warping (DTW)** algorithm. It finds the optimal alignment between two sequences of different lengths (e.g., a fast wave vs a slow wave).
*   **Mathematical Formula (Cumulative Distance Matrix):**
    $$D(i, j) = d(R_i, T_j) + \min \begin{cases} D(i-1, j) \\ D(i, j-1) \\ D(i-1, j-1) \end{cases}$$
    *Where $d(R_i, T_j) = \|R_i - T_j\|$ is the Euclidean distance between sample $i$ of the incoming signal and sample $j$ of the template.*
*   **Auto-Segmentation:** By tracing the minimum distance path $D_{warp}$ backwards through the matrix, we automatically find the exact start and end frame of the gesture in a continuous stream.

#### 3. Inconsistent Segment Masking: Hierarchical Clustering & Star-Padding
Not all parts of a gesture are useful. We use **Hierarchical Clustering** to group temporal points that are consistent across multiple training examples.
*   **Clustering Distance Function:**
    $$f(d_i, d_j) = (d_i - d_j)^2 + \alpha \cdot |i - j|^2$$
    *This groups segments that have both a small DTW distance variance ($d$) and are close together in time ($|i-j|$).*
*   **Star-Padding:** Segments that fail to cluster (the messy start/end of a wave) are replaced with a wildcard `*` in the template. When the DTW algorithm runs, $d(R_i, \text{`*`}) = 0$, meaning the child's messy arm drop isn't penalized in the final score.

#### 4. Classification: Maximum-Margin Hyperplane (MMH) & Second Stage
*   **First Stage (Thresholding):** The algorithm calculates the average DTW distance of the closest 5% of non-target gestures (top line) and the furthest 5% of target gestures (bottom line). The **5% Maximum-Margin Hyperplane** is the exact midpoint. If the warped distance $D_{warp}$ falls below this threshold, the gesture is recognized.
*   **Second Stage (Directionality):** Because absolute rotation $\Delta \theta$ loses direction, we look at the raw accelerometer magnitude. A **Decision Tree** checks if the maximum gravity peak occurs *before* or *after* the minimum valley to distinguish reversible movements (e.g., Swipe Up vs. Swipe Down).

---

## Part 2: Implementation Plan (Version 0.5)

To allow A/B testing and comparative analysis, we will keep the current Random Forest (v1) algorithm fully intact and implement the DTW algorithm (v2) alongside it, with a toggleable option.

### 1. Architecture & Interface Abstraction
- Create a common interface/protocol for the ML backend so the main game loop (`main.py` and `game.py`) doesn't need to know which engine is running.
- **Current System:** `GestureLearningSystem` (in `shared/gesture_learner.py`)
- **New System:** `DTWLearningSystem` (to be created in `shared/dtw_learner.py`)
- **Controller:** A wrapper `GestureEngineManager` that holds both and routes calls (`update`, `try_record`, `get_cursor_delta`) to the currently active engine.

### 2. UI / Configuration Toggle
- Add a new configurable property to `GestureProfile` (or `home.py` configuration screen).
- **Debug HUD Toggle:** Pressing `M` (or a similar key) in the developer HUD will hot-swap between **[ML: RF-v1]** and **[ML: DTW-v2]**.
- Both engines will save training data to distinct subfolders (e.g., `data/gestures/{username}/rf_sessions/` and `data/gestures/{username}/dtw_sessions/`) to avoid cross-contamination of feature vectors.

### 3. New Module: `shared/dtw_learner.py`
This file will contain the implementations for the paper's techniques:

#### A. `OrientationIndependentExtractor`
- Takes the rolling `GestureBuffer`.
- Calculates the $\Delta\theta_i$ time-series vector using the paper's integral formula: $\Delta \theta_i = \sqrt{(\sum \omega_x \Delta t)^2 + (\sum \omega_y \Delta t)^2 + (\sum \omega_z \Delta t)^2}$.

#### B. `DTWEngine` (Segmentation & Classification)
- Implements the standard DTW dynamic programming matrix.
- **Auto-Segmentation:** Runs DTW over the continuous buffer against class templates to find the optimal warp distance ($D_{warp}$) and the ending index.
- **Classification:** Implements the 5% Maximum-Margin Hyperplane (MMH). If $D_{warp} < MMH\_Threshold$, the gesture is detected.

#### C. `TemplateRefiner`
- Runs during `save_and_train()`.
- Picks a beacon instance, runs DTW against all other instances in that class.
- Uses a simple hierarchical clustering (or distance thresholding) to find "inconsistent" sample indices.
- Replaces those indices in the beacon template with `*` (Star-padding) so they contribute 0 to future DTW distance calculations.

#### D. `SecondStageClassifier`
- For reversible movements (e.g., Up vs Down).
- Looks at the raw accelerometer magnitude `abs_ax/ay/az` (low-pass filtered at 5Hz).
- If the maximum peak precedes the minimum valley -> Class A (e.g., Down).
- If the minimum valley precedes the maximum peak -> Class B (e.g., Up).

### 4. Integration & Testing Phase
1. **Implement `dtw_learner.py`:** Write the math and logic in isolation. Add unit tests for the DTW matrix and Star-padding logic.
2. **Engine Wrapper:** Update `games/fruit_ninja/game.py` (and others) to instantiate `GestureEngineManager` instead of `GestureLearningSystem`.
3. **Data Collection:** Add a UI prompt when switching to DTW mode: *"DTW Engine requires new calibration data. Press L to enter Learn Mode."*
4. **Validation:** Use the existing `GestureValidator` cross-validation UI, but route the metrics from the DTW engine to compare Precision/Recall against the Random Forest model.

### 5. Future Considerations
- DTW is computationally more expensive than a Random Forest inference. We will need to monitor the game's FPS. If DTW matrix calculation causes frame drops (since Pygame runs synchronously), we will offload the DTW inference to the existing background `Gesture thread` (`shared/gesture.py`) rather than the main Pygame thread.
