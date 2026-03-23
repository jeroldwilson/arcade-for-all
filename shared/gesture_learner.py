"""
gesture_learner.py — Personal gesture learning system for Fruit Slice

Architecture
────────────
  GestureBuffer       — rolling deque of raw IMU snapshots at ~60 Hz
  SmartRecorder       — captures gesture windows with quality filters:
                         • goal guard    : only record when a fruit is on screen
                         • motion guard  : only record when there is meaningful motion
                         • cooldown guard: enforce minimum time between recordings
                         • erratic guard : reject jittery/random-looking windows
  FeatureExtractor    — converts a window into a 25-feature vector
  IntentLabeler       — labels each window by direction from blade to nearest fruit
  GestureDataset      — JSON sessions saved to data/gestures/sessions/
  GestureModel        — sklearn RandomForestClassifier, saved to data/gestures/model.pkl
  GestureLearningSystem — top-level coordinator used by FruitNinjaGame
"""

import json
import math
import time
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── Constants ─────────────────────────────────────────────────────────────────

# Rolling buffer: 18 frames @ ~60 Hz ≈ 300 ms window
BUFFER_FRAMES    = 18

# SmartRecorder quality thresholds
MOTION_MAG_MIN   = 25.0   # °/s minimum total gyro magnitude to count as intentional
COOLDOWN_SECS    = 0.6    # minimum seconds between successive recordings
ERRATIC_STD_MAX  = 180.0  # maximum gyro-magnitude std (rejects random rapid shaking)

# Minimum labelled samples before training can succeed
MIN_TRAIN_SAMPLES = 10

DATA_DIR = Path(__file__).parent.parent / "data" / "gestures"


def _user_data_dir(username: str) -> Path:
    """Return per-user gesture data directory, falling back to shared if no username."""
    if username and username not in ("", "Guest"):
        return Path(__file__).parent.parent / "data" / "gestures" / username
    return DATA_DIR


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class IMUSnapshot:
    """One frame of raw IMU data."""
    t:  float                           # monotonic timestamp (s)
    gx: float; gy: float; gz: float     # gyro °/s
    ax: float; ay: float; az: float     # accel g


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
    """Converts a list of IMUSnapshot into a fixed-length 25-feature vector."""

    N_FEATURES = 25

    def extract(self, window: List[IMUSnapshot]) -> Optional[List[float]]:
        if len(window) < 3:
            return None

        n = len(window)
        channels = {
            'gx': [s.gx for s in window],
            'gy': [s.gy for s in window],
            'gz': [s.gz for s in window],
            'ax': [s.ax for s in window],
            'ay': [s.ay for s in window],
            'az': [s.az for s in window],
        }

        feats: List[float] = []

        # Per-channel: mean, std, max_abs  (6 × 3 = 18 features)
        for ch in ('gx', 'gy', 'gz', 'ax', 'ay', 'az'):
            vals = channels[ch]
            mean = sum(vals) / n
            std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
            mabs = max(abs(v) for v in vals)
            feats.extend([mean, std, mabs])

        # Gyro magnitude stats: mean, std, max, range  (4 features)
        gmags   = [math.sqrt(s.gx**2 + s.gy**2 + s.gz**2) for s in window]
        gm_mean = sum(gmags) / n
        gm_std  = math.sqrt(sum((v - gm_mean) ** 2 for v in gmags) / n)
        gm_max  = max(gmags)
        gm_rng  = gm_max - min(gmags)
        feats.extend([gm_mean, gm_std, gm_max, gm_rng])

        # Dominant gyro angle  (1 feature): atan2(mean_gy, mean_gz)
        mean_gy = sum(s.gy for s in window) / n
        mean_gz = sum(s.gz for s in window) / n
        feats.append(math.atan2(mean_gy, mean_gz))

        # Energy: gyro RMS, accel RMS  (2 features)
        gyro_e  = math.sqrt(sum(s.gx**2 + s.gy**2 + s.gz**2 for s in window) / n)
        accel_e = math.sqrt(sum(s.ax**2 + s.ay**2 + s.az**2 for s in window) / n)
        feats.extend([gyro_e, accel_e])

        assert len(feats) == self.N_FEATURES
        return feats


# ── Intent labelling ──────────────────────────────────────────────────────────

class IntentLabeler:
    """
    Labels a gesture by the direction from the blade to the nearest fruit.
    This encodes *goal intent* rather than raw hand motion — important for
    users with movement disorders where the physical gesture may not match the
    desired direction but the goal (fruit) is always clear.
    """

    DIRECTIONS = ("right", "left", "up", "down")

    @staticmethod
    def label(
        blade_xy: Tuple[float, float],
        fruits_xy: List[Tuple[float, float]],
    ) -> Optional[str]:
        """Returns direction label, or None if no fruits present."""
        if not fruits_xy:
            return None
        bx, by = blade_xy
        nearest = min(fruits_xy, key=lambda f: math.hypot(f[0] - bx, f[1] - by))
        dx = nearest[0] - bx
        dy = nearest[1] - by   # positive = fruit is below blade (screen coords)
        if abs(dx) >= abs(dy):
            return "right" if dx > 0 else "left"
        else:
            return "down" if dy > 0 else "up"


# ── Smart recorder ────────────────────────────────────────────────────────────

class SmartRecorder:
    """
    Records gesture windows only when all four quality guards pass:
      1. Goal guard    : at least one fruit is on screen
      2. Motion guard  : gyro magnitude exceeds MOTION_MAG_MIN
      3. Cooldown guard: minimum COOLDOWN_SECS since last recording
      4. Erratic guard : gyro std below ERRATIC_STD_MAX (rejects random shaking)
    """

    def __init__(self, buffer: GestureBuffer, extractor: FeatureExtractor):
        self._buf       = buffer
        self._extractor = extractor
        self._last_rec  = 0.0
        self.recordings: List[Dict] = []

    def try_record(
        self,
        gs,                                    # GestureState
        blade_xy: Tuple[float, float],
        fruits_xy: List[Tuple[float, float]],
    ) -> bool:
        """Attempt to record a gesture window. Returns True if recorded."""

        # 1. Goal guard
        if not fruits_xy:
            return False

        # 2. Cooldown guard
        now = time.monotonic()
        if now - self._last_rec < COOLDOWN_SECS:
            return False

        # 3. Motion guard
        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)
        if gyro_mag < MOTION_MAG_MIN:
            return False

        window = self._buf.snapshot()
        if len(window) < 6:
            return False

        # 4. Erratic guard — reject windows with very high gyro std
        mags   = [math.sqrt(s.gx**2 + s.gy**2 + s.gz**2) for s in window]
        mean_m = sum(mags) / len(mags)
        std_m  = math.sqrt(sum((v - mean_m) ** 2 for v in mags) / len(mags))
        if std_m > ERRATIC_STD_MAX:
            return False

        features = self._extractor.extract(window)
        if features is None:
            return False

        label = IntentLabeler.label(blade_xy, fruits_xy)
        if label is None:
            return False

        self.recordings.append({"features": features, "label": label, "time": now})
        self._last_rec = now
        return True

    def clear(self) -> None:
        self.recordings.clear()


# ── Dataset ───────────────────────────────────────────────────────────────────

class GestureDataset:
    """Persists gesture recordings as JSON session files."""

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
        """Load all saved sessions and return (X, y) for training."""
        X: List[List[float]] = []
        y: List[str]         = []
        if not self.SESSION_DIR.exists():
            return X, y
        for fp in sorted(self.SESSION_DIR.glob("session_*.json")):
            try:
                recs = json.loads(fp.read_text())
                for r in recs:
                    X.append(r["features"])
                    y.append(r["label"])
            except Exception as exc:
                print(f"[gesture_learner] Could not load {fp.name}: {exc}")
        return X, y


# ── Model ─────────────────────────────────────────────────────────────────────

class GestureModel:
    """RandomForest classifier for personal gesture prediction."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.MODEL_PATH = data_dir / "model.pkl"
        self._clf = None

    @property
    def ready(self) -> bool:
        return self._clf is not None

    def train(self, X: List[List[float]], y: List[str]) -> bool:
        """Fit (or re-fit) the classifier. Returns True on success."""
        if len(X) < MIN_TRAIN_SAMPLES:
            return False
        try:
            from sklearn.ensemble import RandomForestClassifier  # deferred import
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

    def predict(self, features: List[float]) -> Optional[str]:
        if self._clf is None:
            return None
        try:
            return self._clf.predict([features])[0]
        except Exception:
            return None

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
                self._clf = pickle.load(f)
            print("[gesture_learner] Loaded existing model.")
            return True
        except Exception as exc:
            print(f"[gesture_learner] Load failed: {exc}")
            return False


# ── Top-level coordinator ─────────────────────────────────────────────────────

class GestureLearningSystem:
    """
    Top-level coordinator used by FruitNinjaGame in learn/test submodes.

    Call update()         every frame to feed raw IMU data into the buffer.
    Call try_record()     in learn mode to attempt gesture capture.
    Call get_cursor_delta() in test mode to drive the cursor via prediction.
    Call save_and_train() when the game session ends.
    """

    # Unit vectors for each predicted direction
    _DIR_VECTORS = {
        "right": ( 1.0,  0.0),
        "left":  (-1.0,  0.0),
        "up":    ( 0.0, -1.0),
        "down":  ( 0.0,  1.0),
    }

    # Dead-zone for test-mode cursor movement (°/s)
    _TEST_DEAD = 15.0

    def __init__(self, username: str = ""):
        data_dir = _user_data_dir(username)
        self.buffer    = GestureBuffer()
        self.extractor = FeatureExtractor()
        self.recorder  = SmartRecorder(self.buffer, self.extractor)
        self.dataset   = GestureDataset(data_dir)
        self.model     = GestureModel(data_dir)
        self.model.load()
        self._last_rec_flash = 0.0

    # ── Per-frame feed ─────────────────────────────────────────────────────────

    def update(self, gs) -> None:
        """Push the latest GestureState into the rolling IMU buffer."""
        self.buffer.push(IMUSnapshot(
            t  = time.monotonic(),
            gx = gs.abs_gx, gy = gs.abs_gy, gz = gs.abs_gz,
            ax = gs.abs_ax, ay = gs.abs_ay, az = gs.abs_az,
        ))

    # ── Learn mode ─────────────────────────────────────────────────────────────

    def try_record(
        self,
        gs,
        blade_xy: Tuple[float, float],
        fruits_xy: List[Tuple[float, float]],
    ) -> bool:
        """Attempt to capture a labelled gesture. Returns True if recorded."""
        recorded = self.recorder.try_record(gs, blade_xy, fruits_xy)
        if recorded:
            self._last_rec_flash = time.monotonic()
        return recorded

    # ── Test mode ──────────────────────────────────────────────────────────────

    def get_cursor_delta(
        self,
        gs,
        scale_x: float,
        scale_y: float,
        dt: float,
    ) -> Tuple[float, float]:
        """
        Predict intended direction and return cursor (dx, dy) for this frame.
        Falls back to raw gyro mapping when the model is not ready.
        Returns (0, 0) when the wrist is still.
        """
        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)
        if gyro_mag < self._TEST_DEAD:
            return 0.0, 0.0

        if not self.model.ready:
            # Fall back: standard gyro mapping
            gz = gs.abs_gz if abs(gs.abs_gz) >= self._TEST_DEAD else 0.0
            gy = gs.abs_gy if abs(gs.abs_gy) >= self._TEST_DEAD else 0.0
            return gz * scale_x * dt, -gy * scale_y * dt

        window   = self.buffer.snapshot()
        features = self.extractor.extract(window)
        if features is None:
            return 0.0, 0.0

        direction = self.model.predict(features)
        if direction is None:
            return 0.0, 0.0

        dx_u, dy_u = self._DIR_VECTORS.get(direction, (0.0, 0.0))
        speed = gyro_mag * (scale_x + scale_y) * 0.5 * dt
        return dx_u * speed, dy_u * speed

    # ── Session end ────────────────────────────────────────────────────────────

    def save_and_train(self) -> bool:
        """
        Save current session recordings and retrain on all historical data.
        Returns True if training succeeded.
        """
        if self.recorder.recordings:
            self.dataset.save_session(self.recorder.recordings)
            self.recorder.clear()
        X, y = self.dataset.as_xy()
        if len(X) >= MIN_TRAIN_SAMPLES:
            ok = self.model.train(X, y)
            if ok:
                print(f"[gesture_learner] Model retrained on {len(X)} samples.")
            return ok
        print(f"[gesture_learner] Not enough samples to train ({len(X)}/{MIN_TRAIN_SAMPLES}).")
        return False

    # ── UI helpers ─────────────────────────────────────────────────────────────

    @property
    def rec_flash_active(self) -> bool:
        """True for 0.4 s after each successful recording (drives REC indicator)."""
        return time.monotonic() - self._last_rec_flash < 0.4

    @property
    def total_recordings(self) -> int:
        return len(self.recorder.recordings)

    @property
    def model_ready(self) -> bool:
        return self.model.ready
