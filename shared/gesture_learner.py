"""
gesture_learner.py — Clinical-grade-inspired personal gesture learning for Fruit Slice

Architecture
────────────
  GestureBuffer       — rolling deque of raw IMU snapshots at ~60 Hz
  SmartRecorder       — event-centered windows with quality guards:
                         • goal guard    : only record when a fruit is on screen
                         • motion guard  : only record when there is meaningful motion
                         • cooldown guard: enforce minimum time between recordings
                         • erratic guard : reject jittery/random-looking windows
                         • balance guard : warn on severe class imbalance
  FeatureExtractor    — 38-feature vector: per-channel stats + temporal features
  IntentLabeler       — labels with ambiguity rejection + trajectory context
  GestureDataset      — versioned JSON sessions with session_id + quality metadata
  GestureModel        — probabilistic RandomForest with confidence-based abstain
  GestureValidator    — session-aware stratified CV with precision/recall/F1/FP-rate
  GestureLearningSystem — top-level coordinator with temporal smoothing + safe fallback

Disclaimer: inspired by clinical-grade robustness principles; NOT a certified medical device.

Feature inventory (USE / REJECT):
  abs_gx, abs_gy, abs_gz  → USE  (primary motion signals, raw gyro)
  abs_ax, abs_ay, abs_az  → USE  (orientation via gravity estimate, low-pass filtered)
  av_magnitude            → USE  (motion intensity summary; redundant but helpful for RF)
  euler_roll, euler_pitch → USE  (stable gravity-referenced orientation)
  euler_yaw               → REJECT (drifts without magnetometer)
  qw/qx/qy/qz             → REJECT (redundant with euler roll/pitch; not exposed in GestureState)
  slice_active/direction  → REJECT (leaky — already classifies the motion we're predicting)
  paddle_velocity/launch/spin → REJECT (processed/downstream signals; redundant + leaky)
  raw_ax, raw_gz          → REJECT (redundant with abs_ versions)
  lin_ax/ay/az (FusionState) → REJECT for now (not exposed in GestureState; future work)

Temporal features added:
  jerk (gx,gy,gz)         → USE  (rate-of-change of rotation captures gesture sharpness)
  zero_crossings (gz,gy)  → USE  (direction changes; distinguishes slash from hold)
  peak_timing_fraction    → USE  (where in window does peak occur; avoids window-edge bias)
  signed_area (gz,gy,gx)  → USE  (net directional integral; correlated with intent direction)
  dominant_axis_ratio     → USE  (horizontal vs vertical dominance)
  pre/post peak mag       → captured implicitly in peak_timing + per-channel stats
"""

import json
import math
import random
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── sklearn availability — checked once at import, NEVER faked ────────────────
try:
    from sklearn.ensemble import RandomForestClassifier
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

# Schema version — increment when feature format changes (old records are skipped)
SCHEMA_VERSION = 2

# Rolling pre-trigger buffer: 30 frames @ ~60 Hz ≈ 500 ms look-back
BUFFER_FRAMES    = 30
# Frames extracted centered on motion peak
EVENT_FRAMES     = 18

# SmartRecorder quality thresholds
MOTION_MAG_MIN   = 25.0    # °/s minimum gyro magnitude for intentional motion
COOLDOWN_SECS    = 0.6     # minimum seconds between successive recordings
ERRATIC_STD_MAX  = 180.0   # maximum gyro-mag std (rejects random shaking)

# Labeling: require one spatial axis to dominate by this fraction (rejects diagonals)
# threshold = 0.5 + AMBIGUITY_MARGIN; with 0.25 → must be ≥75% along one axis
AMBIGUITY_MARGIN = 0.25

# Log a warning when any class has this many × more samples than the smallest class
BALANCE_WARN_RATIO = 3.0

MIN_TRAIN_SAMPLES = 10

DATA_DIR = Path(__file__).parent.parent / "data" / "gestures"


def _user_data_dir(username: str) -> Path:
    if username and username not in ("", "Guest"):
        return Path(__file__).parent.parent / "data" / "gestures" / username
    return DATA_DIR


# ── Accessibility / safety profiles ──────────────────────────────────────────

@dataclass
class GestureProfile:
    """Configurable inference profile for different accessibility needs."""
    dead_zone: float = 15.0             # °/s dead-zone for test-mode cursor
    confidence_threshold: float = 0.55  # abstain below this confidence
    smoothing_frames: int = 4           # frames for temporal majority vote
    max_speed_scale: float = 1.0        # cap on cursor speed multiplier


PROFILE_STANDARD   = GestureProfile(
    dead_zone=15.0, confidence_threshold=0.55, smoothing_frames=4, max_speed_scale=1.0)
PROFILE_ACCESSIBLE = GestureProfile(
    dead_zone=6.0,  confidence_threshold=0.45, smoothing_frames=6, max_speed_scale=0.75)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class IMUSnapshot:
    """One frame of raw IMU data with optional fusion outputs."""
    t:  float
    gx: float; gy: float; gz: float      # gyro °/s (raw)
    ax: float; ay: float; az: float      # accel g (low-pass filtered ≈ gravity)
    euler_roll:  float = 0.0             # degrees — stable, gravity-referenced
    euler_pitch: float = 0.0            # degrees — stable, gravity-referenced


class GestureBuffer:
    """Thread-safe rolling window of IMU snapshots."""

    def __init__(self, maxlen: int = BUFFER_FRAMES):
        self._buf: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, snap: IMUSnapshot) -> None:
        with self._lock:
            self._buf.append(snap)

    def snapshot(self) -> List[IMUSnapshot]:
        with self._lock:
            return list(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


# ── Feature extraction ────────────────────────────────────────────────────────

class FeatureExtractor:
    """
    Converts a list of IMUSnapshot into a fixed-length 38-feature vector.

    Index  Description
    ─────  ──────────────────────────────────────────────────────────────
     0-17  Per-channel mean/std/max_abs for gx,gy,gz,ax,ay,az   (6×3=18)
    18-21  Gyro magnitude mean/std/max/range                      (4)
      22   Dominant gyro angle atan2(mean_gy, mean_gz)            (1)
    23-24  Gyro RMS, accel RMS (energy)                           (2)
    25-27  Jerk: abs mean of frame-to-frame diffs for gx,gy,gz   (3)
    28-29  Zero crossings: gz, gy                                 (2)
      30   Peak timing fraction (peak_idx / (n-1))                (1)
    31-33  Signed area: sum(gz), sum(gy), sum(gx)                 (3)
      34   Dominant axis ratio abs(gz)/(abs(gz)+abs(gy)+eps)      (1)
    35-36  Euler roll mean, pitch mean                            (2)
      37   Gyro magnitude at peak frame                           (1)
    ─────  ─────────────────────────────────────────────────────────────
           Total: 38
    """

    N_FEATURES = 38

    def extract(self, window: List[IMUSnapshot]) -> Optional[List[float]]:
        if len(window) < 3:
            return None

        n = len(window)
        gx_v = [s.gx for s in window]
        gy_v = [s.gy for s in window]
        gz_v = [s.gz for s in window]
        ax_v = [s.ax for s in window]
        ay_v = [s.ay for s in window]
        az_v = [s.az for s in window]

        feats: List[float] = []

        # Per-channel stats: mean, std, max_abs  (6 × 3 = 18)
        for vals in (gx_v, gy_v, gz_v, ax_v, ay_v, az_v):
            mean = sum(vals) / n
            std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
            mabs = max(abs(v) for v in vals)
            feats.extend([mean, std, mabs])

        # Gyro magnitude stats  (4)
        gmags   = [math.sqrt(s.gx**2 + s.gy**2 + s.gz**2) for s in window]
        gm_mean = sum(gmags) / n
        gm_std  = math.sqrt(sum((v - gm_mean) ** 2 for v in gmags) / n)
        gm_max  = max(gmags)
        gm_rng  = gm_max - min(gmags)
        feats.extend([gm_mean, gm_std, gm_max, gm_rng])

        # Dominant gyro angle  (1)
        mean_gy = sum(gy_v) / n
        mean_gz = sum(gz_v) / n
        feats.append(math.atan2(mean_gy, mean_gz))

        # Energy: gyro RMS, accel RMS  (2)
        feats.append(math.sqrt(sum(s.gx**2 + s.gy**2 + s.gz**2 for s in window) / n))
        feats.append(math.sqrt(sum(s.ax**2 + s.ay**2 + s.az**2 for s in window) / n))

        # ── Temporal features ──────────────────────────────────────────────

        # Jerk: abs mean of adjacent-frame differences  (3)
        if n > 1:
            jerk_gx = sum(abs(gx_v[i] - gx_v[i-1]) for i in range(1, n)) / (n - 1)
            jerk_gy = sum(abs(gy_v[i] - gy_v[i-1]) for i in range(1, n)) / (n - 1)
            jerk_gz = sum(abs(gz_v[i] - gz_v[i-1]) for i in range(1, n)) / (n - 1)
        else:
            jerk_gx = jerk_gy = jerk_gz = 0.0
        feats.extend([jerk_gx, jerk_gy, jerk_gz])

        # Zero crossings: gz, gy  (2)
        feats.append(float(sum(1 for i in range(1, n) if gz_v[i-1] * gz_v[i] < 0)))
        feats.append(float(sum(1 for i in range(1, n) if gy_v[i-1] * gy_v[i] < 0)))

        # Peak timing fraction  (1)
        peak_idx = max(range(n), key=lambda i: gmags[i])
        feats.append(peak_idx / max(n - 1, 1))

        # Signed area (integral approx)  (3)
        feats.append(sum(gz_v))
        feats.append(sum(gy_v))
        feats.append(sum(gx_v))

        # Dominant axis ratio  (1)
        eps = 1e-6
        feats.append(abs(mean_gz) / (abs(mean_gz) + abs(mean_gy) + eps))

        # Euler orientation means  (2)
        feats.append(sum(s.euler_roll  for s in window) / n)
        feats.append(sum(s.euler_pitch for s in window) / n)

        # Gyro magnitude at peak frame  (1)
        feats.append(gmags[peak_idx])

        assert len(feats) == self.N_FEATURES, \
            f"Feature count mismatch: expected {self.N_FEATURES}, got {len(feats)}"
        return feats


# ── Intent labelling ──────────────────────────────────────────────────────────

class IntentLabeler:
    """
    Labels a gesture by the direction from the blade to the nearest fruit.
    Rejects ambiguous cases: diagonal directions and trajectory-fruit disagreements.
    """

    DIRECTIONS = ("right", "left", "up", "down")

    @staticmethod
    def label(
        blade_xy: Tuple[float, float],
        fruits_xy: List[Tuple[float, float]],
        blade_history: Optional[List[Tuple[float, float]]] = None,
    ) -> Optional[str]:
        """
        Returns direction label or None if:
          - No fruits present
          - Direction is too diagonal (ambiguous intent)
          - Blade trajectory clearly disagrees with fruit direction
        """
        if not fruits_xy:
            return None

        bx, by = blade_xy
        nearest = min(fruits_xy, key=lambda f: math.hypot(f[0] - bx, f[1] - by))
        dx = nearest[0] - bx
        dy = nearest[1] - by

        abs_dx, abs_dy = abs(dx), abs(dy)
        total = abs_dx + abs_dy
        if total < 1e-6:
            return None

        # Require one axis to dominate by AMBIGUITY_MARGIN (rejects diagonals)
        dom_frac = max(abs_dx, abs_dy) / total
        if dom_frac < (0.5 + AMBIGUITY_MARGIN):
            return None

        direction = ("right" if dx > 0 else "left") if abs_dx >= abs_dy \
                    else ("down" if dy > 0 else "up")

        # Validate against blade trajectory: reject if blade moved opposite to fruit
        if blade_history and len(blade_history) >= 3:
            traj_dx = blade_history[-1][0] - blade_history[0][0]
            traj_dy = blade_history[-1][1] - blade_history[0][1]
            if math.hypot(traj_dx, traj_dy) > 20:
                if direction == "right" and traj_dx < -20: return None
                if direction == "left"  and traj_dx >  20: return None
                if direction == "down"  and traj_dy < -20: return None
                if direction == "up"    and traj_dy >  20: return None

        return direction


# ── Smart recorder ────────────────────────────────────────────────────────────

class SmartRecorder:
    """
    Records event-centered gesture windows with quality guards.
    Tracks class balance and blade trajectory for context-aware labeling.
    """

    def __init__(self, buffer: GestureBuffer, extractor: FeatureExtractor):
        self._buf           = buffer
        self._extractor     = extractor
        self._last_rec      = 0.0
        self._blade_history: deque = deque(maxlen=10)
        self._class_counts: Dict[str, int] = {d: 0 for d in IntentLabeler.DIRECTIONS}
        self.recordings: List[Dict] = []

    def update_blade_history(self, blade_xy: Tuple[float, float]) -> None:
        self._blade_history.append(blade_xy)

    @property
    def class_balance_ok(self) -> bool:
        counts = [v for v in self._class_counts.values() if v > 0]
        if len(counts) < 2:
            return True
        return max(counts) / min(counts) < BALANCE_WARN_RATIO

    @property
    def class_counts(self) -> Dict[str, int]:
        return dict(self._class_counts)

    def try_record(
        self,
        gs,
        blade_xy: Tuple[float, float],
        fruits_xy: List[Tuple[float, float]],
        session_id: str = "",
        mode: str = "standard",
    ) -> bool:
        """Attempt to record an event-centered gesture window. Returns True if recorded."""

        if not fruits_xy:
            return False

        now = time.monotonic()
        if now - self._last_rec < COOLDOWN_SECS:
            return False

        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)
        if gyro_mag < MOTION_MAG_MIN:
            return False

        window = self._buf.snapshot()
        if len(window) < 6:
            return False

        mags   = [math.sqrt(s.gx**2 + s.gy**2 + s.gz**2) for s in window]
        mean_m = sum(mags) / len(mags)
        std_m  = math.sqrt(sum((v - mean_m) ** 2 for v in mags) / len(mags))
        if std_m > ERRATIC_STD_MAX:
            return False

        # Event-centering: extract window centered on motion peak
        peak_idx = max(range(len(mags)), key=lambda i: mags[i])
        half     = EVENT_FRAMES // 2
        start    = max(0, peak_idx - half)
        end      = min(len(window), start + EVENT_FRAMES)
        start    = max(0, end - EVENT_FRAMES)
        centered = window[start:end]

        features = self._extractor.extract(centered)
        if features is None:
            return False

        label = IntentLabeler.label(
            blade_xy, fruits_xy,
            blade_history=list(self._blade_history),
        )
        if label is None:
            return False

        quality = {"gyro_peak": mags[peak_idx], "gyro_mean": mean_m, "gyro_std": std_m}

        self.recordings.append({
            "schema_version": SCHEMA_VERSION,
            "features":   features,
            "label":      label,
            "time":       now,
            "session_id": session_id,
            "mode":       mode,
            "quality":    quality,
        })
        self._class_counts[label] = self._class_counts.get(label, 0) + 1
        self._last_rec = now

        if not self.class_balance_ok:
            print(f"[gesture_learner] Class imbalance warning: {self._class_counts}")
        return True

    def clear(self) -> None:
        self.recordings.clear()
        self._class_counts = {d: 0 for d in IntentLabeler.DIRECTIONS}


# ── Dataset ───────────────────────────────────────────────────────────────────

class GestureDataset:
    """Persists versioned gesture recordings as JSON session files."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.SESSION_DIR = data_dir / "sessions"

    def save_session(self, recordings: List[Dict]) -> Optional[Path]:
        if not recordings:
            return None
        self.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        ts   = time.strftime("%Y%m%d_%H%M%S")
        path = self.SESSION_DIR / f"session_{ts}.json"
        with open(path, "w") as f:
            json.dump(recordings, f)
        print(f"[gesture_learner] Saved {len(recordings)} recordings → {path.name}")
        return path

    def as_xy(self) -> Tuple[List[List[float]], List[str]]:
        """Load all saved sessions, return (X, y). Skips schema-incompatible records."""
        X, y, _ = self.as_xy_with_sessions()
        return X, y

    def as_xy_with_sessions(
        self,
    ) -> Tuple[List[List[float]], List[str], List[str]]:
        """
        Load all sessions, return (X, y, session_ids).
        session_ids[i] identifies which recording session sample i came from,
        enabling session-aware train/test splitting in cross-validation.
        Skips records whose feature vector length differs from N_FEATURES.
        """
        X:           List[List[float]] = []
        y:           List[str]         = []
        session_ids: List[str]         = []
        expected = FeatureExtractor.N_FEATURES
        skipped  = 0

        if not self.SESSION_DIR.exists():
            return X, y, session_ids

        for fp in sorted(self.SESSION_DIR.glob("session_*.json")):
            session_name = fp.stem
            try:
                recs = json.loads(fp.read_text())
                for r in recs:
                    feats = r.get("features", [])
                    label = r.get("label", "")
                    if len(feats) != expected or not label:
                        skipped += 1
                        continue
                    X.append(feats)
                    y.append(label)
                    session_ids.append(r.get("session_id") or session_name)
            except Exception as exc:
                print(f"[gesture_learner] Could not load {fp.name}: {exc}")

        if skipped > 0:
            print(
                f"[gesture_learner] Skipped {skipped} records with incompatible feature "
                f"count (expected {expected}). Collect new data to rebuild."
            )
        return X, y, session_ids


# ── Model ─────────────────────────────────────────────────────────────────────

class GestureModel:
    """Probabilistic RandomForest with calibrated confidence and abstain support."""

    def __init__(self, data_dir: Path = DATA_DIR, confidence_threshold: float = 0.55):
        self.MODEL_PATH           = data_dir / "model.pkl"
        self._clf                 = None
        self.confidence_threshold = confidence_threshold

    @property
    def ready(self) -> bool:
        return self._clf is not None and SKLEARN_AVAILABLE

    def set_confidence_threshold(self, threshold: float) -> None:
        self.confidence_threshold = threshold

    def train(self, X: List[List[float]], y: List[str]) -> bool:
        if not SKLEARN_AVAILABLE:
            print("[gesture_learner] scikit-learn not available — cannot train.")
            return False
        if len(X) < MIN_TRAIN_SAMPLES:
            return False
        try:
            clf = RandomForestClassifier(
                n_estimators=60, max_depth=8,
                class_weight="balanced", random_state=42,
            )
            clf.fit(X, y)
            self._clf = clf
            self._save()
            return True
        except Exception as exc:
            print(f"[gesture_learner] Training failed: {exc}")
            return False

    def predict_with_confidence(
        self, features: List[float],
    ) -> Tuple[Optional[str], float]:
        """
        Returns (direction, confidence) or (None, confidence) to abstain.
        Abstains when confidence is below threshold or sklearn unavailable.
        """
        if self._clf is None or not SKLEARN_AVAILABLE:
            return None, 0.0
        try:
            proba    = self._clf.predict_proba([features])[0]
            best_idx = int(max(range(len(proba)), key=lambda i: proba[i]))
            conf     = float(proba[best_idx])
            if conf < self.confidence_threshold:
                return None, conf
            return str(self._clf.classes_[best_idx]), conf
        except Exception:
            return None, 0.0

    def predict(self, features: List[float]) -> Optional[str]:
        direction, _ = self.predict_with_confidence(features)
        return direction

    def _save(self) -> None:
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            import pickle
            with open(self.MODEL_PATH, "wb") as f:
                pickle.dump(self._clf, f)
        except Exception as exc:
            print(f"[gesture_learner] Save failed: {exc}")

    def load(self) -> bool:
        if not self.MODEL_PATH.exists():
            return False
        try:
            import pickle
            with open(self.MODEL_PATH, "rb") as f:
                clf = pickle.load(f)
            # Discard model if feature count no longer matches extractor
            expected = FeatureExtractor.N_FEATURES
            if hasattr(clf, 'n_features_in_') and clf.n_features_in_ != expected:
                print(
                    f"[gesture_learner] Saved model has {clf.n_features_in_} features, "
                    f"need {expected} — discarding. Press L to collect new data."
                )
                return False
            self._clf = clf
            print("[gesture_learner] Loaded existing model.")
            return True
        except Exception as exc:
            print(f"[gesture_learner] Load failed: {exc}")
            return False


# ── Validation ────────────────────────────────────────────────────────────────

DIRECTIONS = ("right", "left", "up", "down")


@dataclass
class ValidationResult:
    """Results from session-aware k-fold cross-validation."""
    overall_accuracy: float
    per_class: Dict[str, Dict]            # {dir: {precision, recall, f1, accuracy, support, tp, fp, fn}}
    confusion: Dict[str, Dict[str, int]]
    n_samples: int
    n_sessions: int
    weakest_class: str                    # direction with lowest F1
    fp_rate: float = 0.0                  # macro-averaged false positive rate
    abstain_rate: float = 0.0             # fraction of CV test samples that abstained
    latency_ms: float = 0.0              # estimated per-prediction latency (ms)
    cv_folds_used: int = 0
    error: str = ""


class GestureValidator:
    """
    Session-aware stratified k-fold cross-validation.

    Critical invariant: all samples from the same recording session are assigned
    to the same fold, preventing leakage from temporally-correlated samples.
    Reports precision, recall, F1, FP rate, abstain rate, and latency estimate.
    """

    def __init__(self, dataset: "GestureDataset", n_folds: int = 5):
        self._dataset = dataset
        self._n_folds = n_folds
        self.result: Optional[ValidationResult] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.result   = None
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.result = self._validate()
        except Exception as exc:
            self.result = ValidationResult(
                overall_accuracy=0.0, per_class={}, confusion={},
                n_samples=0, n_sessions=0, weakest_class="",
                error=str(exc),
            )
        finally:
            self._running = False

    def _validate(self) -> ValidationResult:
        if not SKLEARN_AVAILABLE:
            return ValidationResult(
                overall_accuracy=0.0, per_class={}, confusion={},
                n_samples=0, n_sessions=0, weakest_class="",
                error="scikit-learn not installed (pip install scikit-learn)",
            )

        X, y, session_ids = self._dataset.as_xy_with_sessions()
        n_samples = len(X)
        unique_sessions = list(dict.fromkeys(session_ids))  # order-preserving dedupe
        n_sessions = len(unique_sessions)

        if n_samples < MIN_TRAIN_SAMPLES:
            return ValidationResult(
                overall_accuracy=0.0,
                per_class={d: {"precision": 0.0, "recall": 0.0, "f1": 0.0,
                               "accuracy": 0.0, "support": 0, "tp": 0, "fp": 0, "fn": 0}
                           for d in DIRECTIONS},
                confusion={d: {d2: 0 for d2 in DIRECTIONS} for d in DIRECTIONS},
                n_samples=n_samples, n_sessions=n_sessions, weakest_class="",
                error=f"Need ≥{MIN_TRAIN_SAMPLES} samples (have {n_samples})",
            )

        # Session-aware fold assignment: whole sessions go to one fold
        k = max(2, min(self._n_folds, n_sessions))
        session_to_fold = {s: i % k for i, s in enumerate(sorted(unique_sessions))}
        sample_folds    = [session_to_fold[sid] for sid in session_ids]

        all_true:    List[str] = []
        all_pred:    List[str] = []
        abstain_count = 0
        latencies:   List[float] = []
        folds_used   = 0

        for fold_i in range(k):
            X_train = [X[i] for i, f in enumerate(sample_folds) if f != fold_i]
            y_train = [y[i] for i, f in enumerate(sample_folds) if f != fold_i]
            X_test  = [X[i] for i, f in enumerate(sample_folds) if f == fold_i]
            y_test  = [y[i] for i, f in enumerate(sample_folds) if f == fold_i]

            if not X_train or not X_test:
                continue

            try:
                clf = RandomForestClassifier(
                    n_estimators=30, max_depth=8,
                    class_weight="balanced", random_state=42,
                )
                clf.fit(X_train, y_train)

                t0 = time.monotonic()
                for feat, true_lbl in zip(X_test, y_test):
                    proba    = clf.predict_proba([feat])[0]
                    best_idx = int(max(range(len(proba)), key=lambda j: proba[j]))
                    conf     = float(proba[best_idx])
                    if conf < 0.55:
                        abstain_count += 1
                    # Include in metrics regardless of abstain (abstain = low-confidence pred)
                    all_pred.append(str(clf.classes_[best_idx]))
                    all_true.append(true_lbl)
                t1 = time.monotonic()
                if X_test:
                    latencies.append((t1 - t0) / len(X_test) * 1000)
                folds_used += 1
            except Exception as exc:
                print(f"[gesture_learner] Fold {fold_i} failed: {exc}")

        if not all_true:
            return ValidationResult(
                overall_accuracy=0.0, per_class={}, confusion={},
                n_samples=n_samples, n_sessions=n_sessions, weakest_class="",
                error="CV produced no predictions — check data quality and session count",
                cv_folds_used=folds_used,
            )

        overall_accuracy = sum(t == p for t, p in zip(all_true, all_pred)) / len(all_true)
        abstain_rate     = abstain_count / len(all_true)
        latency_ms       = sum(latencies) / len(latencies) if latencies else 0.0

        dirs = [d for d in DIRECTIONS if d in set(y)]
        confusion: Dict[str, Dict[str, int]] = {d: {d2: 0 for d2 in dirs} for d in dirs}
        for t, p in zip(all_true, all_pred):
            if t in confusion and p in confusion.get(t, {}):
                confusion[t][p] += 1

        per_class: Dict[str, Dict] = {}
        weakest_f1    = 2.0
        weakest_class = ""
        fp_rates: List[float] = []

        for d in dirs:
            tp  = confusion[d].get(d, 0)
            fn  = sum(confusion[d].get(p, 0) for p in dirs if p != d)
            fp  = sum(confusion.get(t, {}).get(d, 0) for t in dirs if t != d)
            tn  = sum(
                confusion.get(t, {}).get(p, 0)
                for t in dirs for p in dirs if t != d and p != d
            )
            support   = tp + fn
            acc       = tp / support if support > 0 else 0.0
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1        = 2 * precision * recall / (precision + recall) \
                        if (precision + recall) > 0 else 0.0
            fp_rate_c = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            fp_rates.append(fp_rate_c)

            per_class[d] = {
                "precision": precision, "recall": recall, "f1": f1,
                "accuracy":  acc,       "support": support,
                "tp": tp, "fp": fp, "fn": fn,
            }
            if f1 < weakest_f1:
                weakest_f1    = f1
                weakest_class = d

        fp_rate = sum(fp_rates) / len(fp_rates) if fp_rates else 0.0

        return ValidationResult(
            overall_accuracy=overall_accuracy,
            per_class=per_class,
            confusion=confusion,
            n_samples=n_samples,
            n_sessions=n_sessions,
            weakest_class=weakest_class,
            fp_rate=fp_rate,
            abstain_rate=abstain_rate,
            latency_ms=latency_ms,
            cv_folds_used=folds_used,
        )


# ── Top-level coordinator ─────────────────────────────────────────────────────

class GestureLearningSystem:
    """
    Top-level coordinator used by FruitNinjaGame in learn/test submodes.

    Call update()           every frame to feed raw IMU data into the buffer.
    Call try_record()       in learn mode to attempt gesture capture.
    Call get_cursor_delta() in test mode to drive the cursor via prediction.
    Call save_and_train()   when the game session ends.

    Test-mode cursor convention (matches regular game mode exactly):
      abs_gz (yaw)   → X:  gz > 0 → cursor right   (dx = -gz * scale_x * dt)
      abs_gy (pitch) → Y:  gy > 0 → cursor up       (dy =  gy * scale_y * dt)
    """

    _DIR_VECTORS = {
        "right": ( 1.0,  0.0),
        "left":  (-1.0,  0.0),
        "up":    ( 0.0, -1.0),
        "down":  ( 0.0,  1.0),
    }

    def __init__(self, username: str = "", profile: Optional[GestureProfile] = None):
        data_dir         = _user_data_dir(username)
        self.buffer      = GestureBuffer()
        self.extractor   = FeatureExtractor()
        self._session_id = f"sess_{int(time.time())}"
        self.recorder    = SmartRecorder(self.buffer, self.extractor)
        self.dataset     = GestureDataset(data_dir)
        self.model       = GestureModel(data_dir)
        self.model.load()

        if not self.model.ready:
            X, y = self.dataset.as_xy()
            if len(X) >= MIN_TRAIN_SAMPLES:
                print(f"[gesture_learner] No model; {len(X)} samples found — retraining…")
                self.model.train(X, y)

        self._profile: GestureProfile = profile or PROFILE_STANDARD
        self.model.set_confidence_threshold(self._profile.confidence_threshold)
        self._pred_history: deque = deque(maxlen=self._profile.smoothing_frames)
        self._last_rec_flash = 0.0
        self._validator: Optional[GestureValidator] = None

    def set_profile(self, profile: GestureProfile) -> None:
        self._profile = profile
        self.model.set_confidence_threshold(profile.confidence_threshold)
        self._pred_history = deque(maxlen=profile.smoothing_frames)

    # ── Validation ────────────────────────────────────────────────────────────

    def start_validation(self) -> None:
        self._validator = GestureValidator(self.dataset)
        self._validator.start()

    @property
    def validation_running(self) -> bool:
        return self._validator is not None and self._validator.running

    @property
    def validation_result(self) -> Optional[ValidationResult]:
        return self._validator.result if self._validator else None

    # ── Per-frame feed ────────────────────────────────────────────────────────

    def update(self, gs) -> None:
        """Push the latest GestureState into the rolling IMU buffer."""
        self.buffer.push(IMUSnapshot(
            t           = time.monotonic(),
            gx          = gs.abs_gx,
            gy          = gs.abs_gy,
            gz          = gs.abs_gz,
            ax          = gs.abs_ax,
            ay          = gs.abs_ay,
            az          = gs.abs_az,
            euler_roll  = getattr(gs, 'euler_roll',  0.0),
            euler_pitch = getattr(gs, 'euler_pitch', 0.0),
        ))

    # ── Learn mode ────────────────────────────────────────────────────────────

    def try_record(
        self,
        gs,
        blade_xy: Tuple[float, float],
        fruits_xy: List[Tuple[float, float]],
        mode: str = "standard",
    ) -> bool:
        """Attempt to capture a labelled gesture. Returns True if recorded."""
        self.recorder.update_blade_history(blade_xy)
        recorded = self.recorder.try_record(
            gs, blade_xy, fruits_xy,
            session_id=self._session_id,
            mode=mode,
        )
        if recorded:
            self._last_rec_flash = time.monotonic()
        return recorded

    # ── Test mode ─────────────────────────────────────────────────────────────

    def get_cursor_delta(
        self,
        gs,
        scale_x: float,
        scale_y: float,
        dt: float,
    ) -> Tuple[float, float]:
        """
        Predict intended direction, return cursor (dx, dy).

        Sign convention — identical to regular game mode (game.py _update_blade):
          dx = -gz * scale_x * dt   (yaw right → cursor right)
          dy =  gy * scale_y * dt   (pitch up  → cursor up)

        Falls back to raw gyro (at reduced scale) when:
          - sklearn not available or model not ready
          - model confidence is below threshold (abstain)
          - temporal history has no clear directional majority
        """
        profile  = self._profile
        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)

        if gyro_mag < profile.dead_zone:
            self._pred_history.clear()
            return 0.0, 0.0

        # Per-axis dead-zone for fallback path
        gz = gs.abs_gz if abs(gs.abs_gz) >= profile.dead_zone else 0.0
        gy = gs.abs_gy if abs(gs.abs_gy) >= profile.dead_zone else 0.0

        if not self.model.ready:
            # Fallback: raw gyro, signs match regular mode exactly
            return -gz * scale_x * dt, gy * scale_y * dt

        window   = self.buffer.snapshot()
        features = self.extractor.extract(window)
        if features is None:
            return -gz * scale_x * dt * 0.5, gy * scale_y * dt * 0.5

        direction, _confidence = self.model.predict_with_confidence(features)

        if direction is None:
            # Abstain: reduced-scale raw gyro fallback to stay responsive
            return -gz * scale_x * dt * 0.5, gy * scale_y * dt * 0.5

        # Temporal smoothing: require ≥60% majority over recent history
        self._pred_history.append(direction)
        counts: Dict[str, int] = {}
        for p in self._pred_history:
            counts[p] = counts.get(p, 0) + 1
        best_dir      = max(counts, key=lambda d: counts[d])
        majority_frac = counts[best_dir] / len(self._pred_history)

        if majority_frac < 0.6:
            # No clear consensus — gentle raw-gyro nudge to avoid freezing
            return -gz * scale_x * dt * 0.3, gy * scale_y * dt * 0.3

        dx_u, dy_u = self._DIR_VECTORS.get(best_dir, (0.0, 0.0))
        speed = min(gyro_mag, 300.0) * (scale_x + scale_y) * 0.5 * dt \
                * profile.max_speed_scale
        return dx_u * speed, dy_u * speed

    # ── Session end ───────────────────────────────────────────────────────────

    def save_and_train(self) -> bool:
        if self.recorder.recordings:
            self.dataset.save_session(self.recorder.recordings)
            self.recorder.clear()
        X, y = self.dataset.as_xy()
        if len(X) >= MIN_TRAIN_SAMPLES:
            ok = self.model.train(X, y)
            if ok:
                print(f"[gesture_learner] Model retrained on {len(X)} samples.")
            return ok
        print(f"[gesture_learner] Not enough samples ({len(X)}/{MIN_TRAIN_SAMPLES}).")
        return False

    # ── UI helpers ────────────────────────────────────────────────────────────

    @property
    def rec_flash_active(self) -> bool:
        return time.monotonic() - self._last_rec_flash < 0.4

    @property
    def total_recordings(self) -> int:
        return len(self.recorder.recordings)

    @property
    def model_ready(self) -> bool:
        return self.model.ready

    @property
    def sklearn_available(self) -> bool:
        return SKLEARN_AVAILABLE

    @property
    def class_balance_ok(self) -> bool:
        return self.recorder.class_balance_ok

    @property
    def class_counts(self) -> Dict[str, int]:
        return self.recorder.class_counts

    @property
    def saved_sample_count(self) -> int:
        total = 0
        if not self.dataset.SESSION_DIR.exists():
            return 0
        for fp in self.dataset.SESSION_DIR.glob("session_*.json"):
            try:
                total += len(json.loads(fp.read_text()))
            except Exception:
                pass
        return total
