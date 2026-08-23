"""
gameplay_config.py — Central tuning file for all Accessible (Astra) and Standard (Veera) mode constants.

Edit values here to tune game difficulty without hunting through individual game files.
This module is imported by fruit_ninja/game.py, bricks/game.py, and snake/game.py.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DESIGN INTENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Astra (accessible) mode is designed for users with:
  - Tremors / low-amplitude movements (lower detection thresholds)
  - Fatigue (slower speeds, larger hit zones, auto-aim assist)
  - Reduced intentionality (bigger paddle, forgiving slicing)

Constants marked with [KEY] are the highest-impact difficulty knobs.
See "HOW TO MAKE ASTRA EASIER" at the bottom for a quick-fix guide.
"""

from dataclasses import dataclass


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: GESTURE / SENSOR THRESHOLDS  (drives shared/gesture.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GestureTuning:
    # [KEY] Dead-zone: lateral gravity shift (g) below which paddle is "still".
    #   ~0.05 g ≈ 3°.  Accessible = 0.04 g ≈ 2.3°.
    #   LOWER to respond to weaker tilts. RAISE if phantom drift appears.
    tilt_threshold: float

    # [KEY] Tilt value (g) at which paddle reaches 100% speed.
    #   ~0.5 g ≈ 30°.  Accessible = 0.4 g ≈ 23°.
    #   LOWER to reach full speed with less arm effort.
    tilt_max: float

    # [KEY] Gyro peak (°/s) required to trigger a LAUNCH / flick event.
    #   LOWER to accept weaker flick gestures.
    flick_threshold: float

    # Low-pass alpha for gravity extraction [0–1].
    #   LOWER = heavier filtering = less tremor noise but slower tilt response.
    alpha: float

    # Seconds between repeated LAUNCH events (prevents double-fire).
    launch_cooldown: float

    # Seconds between gesture triggers per axis (accessible game logic).
    gesture_cooldown: float

    # Gyro dead-zone for wrist spin/twist (deg/s).  Set 999 to disable spin.
    twist_dead_zone: float

    # Gyro magnitude (deg/s) below which adaptive baseline can drift.
    gyro_adapt_threshold: float


GESTURE_STANDARD = GestureTuning(
    tilt_threshold       = 0.05,
    tilt_max             = 0.50,
    flick_threshold      = 200.0,
    alpha                = 0.05,
    launch_cooldown      = 0.40,
    gesture_cooldown     = 0.80,
    twist_dead_zone      = 30.0,
    gyro_adapt_threshold = 45.0,
)

GESTURE_ACCESSIBLE = GestureTuning(
    # Picks up smaller wrist tilts
    tilt_threshold       = 0.04,   # RAISE if phantom drift; LOWER for more sensitivity
    # Full speed with ~23 deg tilt instead of ~30 deg
    tilt_max             = 0.40,   # RAISE if too twitchy; LOWER for less effort
    # Weaker flick accepted
    flick_threshold      = 120.0,  # RAISE if accidental launches; LOWER for easier flick
    alpha                = 0.05,   # LOWER (e.g. 0.03) if tremors cause drift
    launch_cooldown      = 1.00,
    gesture_cooldown     = 1.20,
    twist_dead_zone      = 999.0,  # spin DISABLED — safe for contractures/spasticity
    gyro_adapt_threshold = 45.0,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: FRUIT NINJA  (drives games/fruit_ninja/game.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FruitNinjaTuning:
    # Cursor sensitivity (gyro deg/s -> screen pixels).
    # Higher = bigger cursor movement per unit of wrist rotation.
    gyro_scale_x: float
    gyro_scale_y: float

    # [KEY] Gyro magnitude (deg/s) below which cursor doesn't move at all.
    #   Prevents tremor drift.  LOWER = more responsive.  RAISE for less jitter.
    gyro_dead: float

    # [KEY] Gyro magnitude (deg/s) at which cursor trail becomes visible.
    gyro_visible: float

    # [KEY] Gyro magnitude (deg/s) required to count as a slicing motion.
    #   THE MOST IMPACTFUL single knob for Fruit Ninja difficulty.
    #   LOWER = weaker swings still cut fruit.
    gyro_slice: float

    # [KEY] Extra radius (px) added to each fruit for the hit-zone.
    #   50px = blade can be 50px away from centre and still slice.
    slice_extra_px: int

    # Auto-aim: pull strength (px/s) toward nearest fruit when moving (Astra only).
    #   Set 0 to disable.  RAISE for stronger magnetic assist.
    auto_aim_pull: float

    # Intent cone for auto-aim [-1..1].  Pull only applied when moving TOWARD fruit.
    #   0.3 = within ~72 degrees.  LOWER (e.g. 0.1) for a wider assist cone.
    auto_aim_intent_dot: float

    # Spawn timing
    spawn_interval_start: float  # seconds between fruits at game start
    spawn_interval_full: float   # seconds between fruits at full speed

    # Fruit launch speed (px/s) — ramped from SLOW to FULL as score rises
    vy_slow: tuple
    vy_full: tuple
    vx_slow: float
    vx_full: float
    speed_full_score: int  # score at which full speed is reached

    # Session timer and star thresholds
    session_duration_sec: int
    star3_score: int
    star2_score: int


FRUIT_NINJA_STANDARD = FruitNinjaTuning(
    gyro_scale_x         = 5.0,
    gyro_scale_y         = 5.0,
    gyro_dead            = 18.0,
    gyro_visible         = 35.0,
    gyro_slice           = 35.0,
    slice_extra_px       = 8,
    auto_aim_pull        = 0.0,
    auto_aim_intent_dot  = 0.3,
    spawn_interval_start = 2.0,
    spawn_interval_full  = 0.5,
    vy_slow              = (-560, -440),
    vy_full              = (-900, -740),
    vx_slow              = 80.0,
    vx_full              = 190.0,
    speed_full_score     = 40,
    session_duration_sec = 90,
    star3_score          = 30,
    star2_score          = 15,
)

FRUIT_NINJA_ACCESSIBLE = FruitNinjaTuning(
    gyro_scale_x         = 9.0,    # LOWER if cursor flies off screen
    gyro_scale_y         = 9.0,
    gyro_dead            = 6.0,    # RAISE if tremors cause phantom drift
    # [KEY] Deliberate swings register with very little wrist speed:
    gyro_visible         = 8.0,    # deg/s — recommended range: 5-15
    gyro_slice           = 8.0,    # deg/s — recommended range: 5-15
    # [KEY] Large hit-zone:
    slice_extra_px       = 50,     # px  — RAISE to 70-80 for more forgiveness
    # Auto-aim assist:
    auto_aim_pull        = 250.0,  # px/s — RAISE to 350-450 for stronger magnet
    auto_aim_intent_dot  = 0.3,    # LOWER to 0.1 for a wider assist cone
    # Slower fruit cadence:
    spawn_interval_start = 2.8,    # s   — RAISE if overwhelmed at start
    spawn_interval_full  = 1.8,    # s   — RAISE to keep slow speed throughout
    # Gentler fruit arcs:
    vy_slow              = (-650, -580),
    vy_full              = (-740, -660),
    vx_slow              = 70.0,
    vx_full              = 140.0,
    speed_full_score     = 15,     # RAISE to keep easy speed for longer
    session_duration_sec = 60,
    star3_score          = 20,
    star2_score          = 10,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: BRICKS (BREAKOUT)  (drives games/bricks/game.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BricksTuning:
    # Paddle width in pixels (at 800px base resolution).
    paddle_width: int

    # Ball speed (px/s) at game start.
    ball_speed: float

    # [KEY] Tilt (g) above which paddle starts chasing the ball in Astra mode.
    intent_tilt_threshold: float

    # Starting lives.
    lives: int

    # Veera speed ramp (unused in accessible — fixed speed)
    speed_full_score: int
    ball_speed_slow: float
    ball_speed_full: float


BRICKS_STANDARD = BricksTuning(
    paddle_width          = 100,
    ball_speed            = 340.0,
    intent_tilt_threshold = 0.20,
    lives                 = 3,
    speed_full_score      = 500,
    ball_speed_slow       = 160.0,
    ball_speed_full       = 360.0,
)

BRICKS_ACCESSIBLE = BricksTuning(
    paddle_width          = 150,   # px   — RAISE to 180-200 for very easy
    ball_speed            = 240.0, # px/s — LOWER to 180 for more reaction time
    intent_tilt_threshold = 0.20,  # g    — LOWER to 0.12 for stronger paddle assist
    lives                 = 5,     # RAISE further if needed
    speed_full_score      = 500,
    ball_speed_slow       = 160.0,
    ball_speed_full       = 360.0,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: SNAKE  (drives games/snake/game.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SnakeTuning:
    # Seconds per grid step — RAISE for a slower snake.
    move_interval: float

    # [KEY] Tilt magnitude (g) to register a direction change.
    #   LOWER = easier to steer with small tilts.
    tilt_threshold: float

    # Seconds between gesture triggers per axis (prevents rapid accidental turns).
    gesture_cooldown: float

    # Veera ramp (unused in accessible)
    speed_full_score: int
    move_interval_slow: float
    move_interval_full: float


SNAKE_STANDARD = SnakeTuning(
    move_interval      = 0.12,
    tilt_threshold     = 0.35,
    gesture_cooldown   = 0.80,
    speed_full_score   = 200,
    move_interval_slow = 0.28,
    move_interval_full = 0.07,
)

SNAKE_ACCESSIBLE = SnakeTuning(
    move_interval      = 0.50,  # s/step — RAISE to 0.65-0.80 for even slower
    tilt_threshold     = 0.25,  # g      — LOWER to 0.15 for very sensitive steering
    gesture_cooldown   = 0.80,  # s      — RAISE to 1.0 if snake turns too easily
    speed_full_score   = 200,
    move_interval_slow = 0.28,
    move_interval_full = 0.07,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: INACTIVITY MONITOR  (drives shared/game_experience.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class InactivityTuning:
    # Seconds of no motion before Wake Up (haptic + LED + message) starts.
    wake_up_sec: float

    # Seconds of no motion before game auto-pauses.
    auto_pause_sec: float

    # Seconds between haptic pulses during wake-up sequence.
    pulse_interval_sec: float


INACTIVITY_CONFIG = InactivityTuning(
    wake_up_sec        = 5.0,   # RAISE (e.g. 8.0) to be more patient
    auto_pause_sec     = 15.0,  # RAISE (e.g. 25.0) to give more time before pause
    pulse_interval_sec = 2.0,
)


# ══════════════════════════════════════════════════════════════════════════════
# HOW TO MAKE ASTRA EASIER — QUICK-FIX GUIDE
# ══════════════════════════════════════════════════════════════════════════════
#
# SYMPTOM: "Makes a move but game doesn't react"
#   -> Lower FRUIT_NINJA_ACCESSIBLE.gyro_slice   (try 5.0 instead of 8.0)
#   -> Lower GESTURE_ACCESSIBLE.flick_threshold  (try 80.0 instead of 120.0)
#   -> Lower GESTURE_ACCESSIBLE.tilt_threshold   (try 0.025 instead of 0.04)
#
# SYMPTOM: "Cursor flies around from tremors"
#   -> Raise FRUIT_NINJA_ACCESSIBLE.gyro_dead    (try 10.0 instead of 6.0)
#   -> Lower GESTURE_ACCESSIBLE.alpha            (try 0.03 instead of 0.05)
#
# SYMPTOM: "Fruit spawns too fast / too many on screen"
#   -> Raise FRUIT_NINJA_ACCESSIBLE.spawn_interval_full  (try 2.2)
#   -> Raise FRUIT_NINJA_ACCESSIBLE.speed_full_score      (try 25)
#
# SYMPTOM: "Blade clearly hits fruit but doesn't slice"
#   -> Raise FRUIT_NINJA_ACCESSIBLE.slice_extra_px       (try 70-80)
#   -> Raise FRUIT_NINJA_ACCESSIBLE.auto_aim_pull        (try 380)
#   -> Lower FRUIT_NINJA_ACCESSIBLE.auto_aim_intent_dot  (try 0.1)
#
# SYMPTOM: "Bricks ball moves too fast to track"
#   -> Lower BRICKS_ACCESSIBLE.ball_speed                (try 180)
#   -> Raise BRICKS_ACCESSIBLE.paddle_width              (try 180-200)
#
# SYMPTOM: "Wake-up fires too quickly while resting"
#   -> Raise INACTIVITY_CONFIG.wake_up_sec               (try 8.0)
#   -> Raise INACTIVITY_CONFIG.auto_pause_sec            (try 25.0)
