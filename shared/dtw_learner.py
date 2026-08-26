import json
import math
import time
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# Shared imports from existing gesture learner
from shared.gesture_learner import (
    IMUSnapshot, 
    GestureBuffer, 
    IntentLabeler, 
    GestureProfile,
    PROFILE_STANDARD,
    DATA_DIR,
    _user_data_dir,
    ValidationResult
)

# Constants
SCHEMA_VERSION_DTW = 1
MIN_TRAIN_SAMPLES = 5  # DTW doesn't need as many samples as RF

class OrientationIndependentExtractor:
    """
    Converts a list of IMUSnapshot into a 1D time-series curve representing
    cumulative rotation (Total Angle Change Series).
    Perfectly orientation-invariant.
    """
    def __init__(self, dt: float = 1/60.0):
        self.dt = dt

    def extract(self, window: List[IMUSnapshot]) -> List[float]:
        if not window:
            return []
        
        curve = []
        sum_wx, sum_wy, sum_wz = 0.0, 0.0, 0.0
        
        for s in window:
            sum_wx += s.gx * self.dt
            sum_wy += s.gy * self.dt
            sum_wz += s.gz * self.dt
            # Magnitude of the cumulative rotation vector
            theta_i = math.sqrt(sum_wx**2 + sum_wy**2 + sum_wz**2)
            curve.append(theta_i)
            
        return curve

class DTWEngine:
    """
    Dynamic Time Warping sequence alignment.
    Supports "star-padding" where template can have None elements representing 
    inconsistent segments (wildcards) that cost 0 to match.
    """
    @staticmethod
    def distance(seq1: List[float], seq2: List[Optional[float]], max_window: int = 10) -> float:
        """
        seq1: Incoming feature curve
        seq2: Template curve (may contain None for star-padding)
        max_window: Sakoe-Chiba band width to speed up computation
        """
        n, m = len(seq1), len(seq2)
        if n == 0 or m == 0:
            return float('inf')
            
        # Initialize DTW matrix
        dtw = [[float('inf')] * (m + 1) for _ in range(n + 1)]
        dtw[0][0] = 0
        
        for i in range(1, n + 1):
            start = max(1, i - max_window)
            end = min(m, i + max_window)
            for j in range(start, end + 1):
                # Star padding: if template has None, cost is 0
                if seq2[j-1] is None:
                    cost = 0.0
                else:
                    cost = abs(seq1[i-1] - seq2[j-1])
                
                dtw[i][j] = cost + min(
                    dtw[i-1][j],    # insertion
                    dtw[i][j-1],    # deletion
                    dtw[i-1][j-1]   # match
                )
        
        # We normalize by the path length approximation (n+m) to allow 
        # comparing distances of different length gestures
        return dtw[n][m] / (n + m)
        
    @staticmethod
    def auto_segment(buffer_curve: List[float], template: List[Optional[float]]) -> Tuple[float, int, int]:
        """
        Finds the best matching sub-sequence of the buffer against the template.
        Returns: (min_distance, start_idx, end_idx)
        This is a continuous DTW approach (Subsequence DTW).
        """
        n, m = len(buffer_curve), len(template)
        if n < m // 2 or m == 0:
            return float('inf'), 0, 0
            
        dtw = [[float('inf')] * (m + 1) for _ in range(n + 1)]
        
        # For subsequence DTW, the first row is initialized to 0
        # which means the template can start matching at any point in the buffer
        for i in range(n + 1):
            dtw[i][0] = 0
            
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                if template[j-1] is None:
                    cost = 0.0
                else:
                    cost = abs(buffer_curve[i-1] - template[j-1])
                    
                dtw[i][j] = cost + min(
                    dtw[i-1][j],
                    dtw[i][j-1],
                    dtw[i-1][j-1]
                )
                
        # Find the minimum distance in the last column
        min_dist = float('inf')
        end_idx = n
        for i in range(1, n + 1):
            if dtw[i][m] < min_dist:
                min_dist = dtw[i][m]
                end_idx = i
                
        # To find start_idx precisely requires backtracking, but for simplicity
        # we can estimate it based on the template length and stretching constraint.
        # We'll just approximate it for window extraction if needed.
        start_idx = max(0, end_idx - m)
        
        return min_dist / m, start_idx, end_idx

class TemplateRefiner:
    """
    Finds inconsistent segments across multiple instances of the same gesture 
    and replaces them with wildcards (star-padding).
    """
    @staticmethod
    def refine(instances: List[List[float]], alpha: float = 10.0) -> List[Optional[float]]:
        if not instances:
            return []
        if len(instances) == 1:
            return [x for x in instances[0]]
            
        # 1. Pick beacon (simplest: the one with median length)
        instances.sort(key=len)
        beacon = instances[len(instances) // 2]
        
        # 2. For every sample in beacon, calculate average distance to warped points in other instances
        # (Simplified: we compare aligned points. For full paper implementation, we'd do full 
        # traceback, but point-wise variance gives a good approximation of inconsistency).
        # We'll pad sequences to the beacon length for easy variance calc.
        
        n = len(beacon)
        variances = [0.0] * n
        
        # Basic variance approximation
        for inst in instances:
            if inst is beacon: continue
            
            # Simple resampling to beacon length
            m = len(inst)
            for i in range(n):
                # map i to nearest j in inst
                j = min(m - 1, int(i * m / n))
                variances[i] += abs(beacon[i] - inst[j])
                
        for i in range(n):
            variances[i] /= (len(instances) - 1)
            
        # 3. Mask out the top 25% most variable points (the inconsistent segments)
        sorted_vars = sorted(variances)
        threshold = sorted_vars[int(n * 0.75)] if n > 0 else 0
        
        refined_template: List[Optional[float]] = []
        for i in range(n):
            if variances[i] > threshold and variances[i] > 10.0:
                refined_template.append(None) # Star pad
            else:
                refined_template.append(beacon[i])
                
        return refined_template

class SecondStageClassifier:
    """
    Resolves directional ambiguity for reversible gestures (e.g. up vs down)
    by analyzing accelerometer peaks and valleys order.
    """
    @staticmethod
    def resolve_direction(window: List[IMUSnapshot], candidates: List[str]) -> str:
        # If there's only 1 candidate, or candidates aren't reversible pairs, fallback.
        if len(candidates) != 2:
            return candidates[0]
            
        # Look at raw accel magnitudes
        n = len(window)
        if n < 3:
            return candidates[0]
            
        amags = [math.sqrt(s.ax**2 + s.ay**2 + s.az**2) for s in window]
        
        # Find absolute max peak and min valley
        max_idx = amags.index(max(amags))
        min_idx = amags.index(min(amags))
        
        # Reversible pairs logic
        if set(candidates) == {"up", "down"}:
            # For a downward swipe, typically you accelerate down (helping gravity -> smaller amag)
            # then decelerate (against gravity -> larger amag peak). So min_idx < max_idx = down
            return "down" if min_idx < max_idx else "up"
            
        if set(candidates) == {"left", "right"}:
            # For horizontal, gyro dominant axis sign is more reliable
            gz_mean = sum(s.gz for s in window) / n
            return "right" if gz_mean > 0 else "left"
            
        return candidates[0]


class DTWDataset:
    def __init__(self, data_dir: Path):
        self.SESSION_DIR = data_dir / "dtw_sessions"
        
    def save_session(self, recordings: List[Dict]) -> Optional[Path]:
        if not recordings: return None
        self.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.SESSION_DIR / f"session_{ts}.json"
        with open(path, "w") as f:
            json.dump(recordings, f)
        print(f"[dtw_learner] Saved {len(recordings)} recordings -> {path.name}")
        return path
        
    def load_all(self) -> Tuple[List[List[float]], List[str], List[List[IMUSnapshot]]]:
        X, y, raw_windows = [], [], []
        if not self.SESSION_DIR.exists(): return X, y, raw_windows
        
        for fp in sorted(self.SESSION_DIR.glob("session_*.json")):
            try:
                recs = json.loads(fp.read_text())
                for r in recs:
                    if "curve" in r and "label" in r:
                        X.append(r["curve"])
                        y.append(r["label"])
                        raw = r.get("raw_window", [])
                        # Reconstruct IMUSnapshots
                        snaps = [IMUSnapshot(**s) for s in raw] if raw else []
                        raw_windows.append(snaps)
            except Exception as e:
                print(f"[dtw_learner] Load error {fp.name}: {e}")
        return X, y, raw_windows

class DTWModel:
    def __init__(self, data_dir: Path):
        self.templates: Dict[str, List[Optional[float]]] = {}
        self.mmh_thresholds: Dict[str, float] = {}
        self.MODEL_PATH = data_dir / "dtw_model.json"
        
    @property
    def ready(self) -> bool:
        return len(self.templates) > 0
        
    def train(self, X: List[List[float]], y: List[str]) -> bool:
        if len(X) < MIN_TRAIN_SAMPLES: return False
        
        # Group by class
        classes = set(y)
        instances_by_class = {c: [] for c in classes}
        for curve, label in zip(X, y):
            instances_by_class[label].append(curve)
            
        # Refine templates
        for c, instances in instances_by_class.items():
            refined = TemplateRefiner.refine(instances)
            self.templates[c] = refined
            
        # Calculate MMH thresholds
        for target_class, template in self.templates.items():
            target_dists = [DTWEngine.distance(c, template) for c, lbl in zip(X, y) if lbl == target_class]
            non_target_dists = [DTWEngine.distance(c, template) for c, lbl in zip(X, y) if lbl != target_class]
            
            if not target_dists: continue
            
            target_dists.sort()
            # bottom line: mean of largest 5% distance samples of target
            k_t = max(1, int(len(target_dists) * 0.05))
            bottom_line = sum(target_dists[-k_t:]) / k_t
            
            if non_target_dists:
                non_target_dists.sort()
                # top line: mean of smallest 5% distance samples of non-target
                k_n = max(1, int(len(non_target_dists) * 0.05))
                top_line = sum(non_target_dists[:k_n]) / k_n
                mmh = (bottom_line + top_line) / 2.0
            else:
                mmh = bottom_line * 1.5 # fallback if no non-targets
                
            self.mmh_thresholds[target_class] = mmh
            
        self._save()
        return True
        
    def _save(self):
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.MODEL_PATH, "w") as f:
            json.dump({
                "templates": self.templates,
                "mmh_thresholds": self.mmh_thresholds
            }, f)
            
    def load(self) -> bool:
        if not self.MODEL_PATH.exists(): return False
        try:
            with open(self.MODEL_PATH, "r") as f:
                data = json.load(f)
                self.templates = data.get("templates", {})
                self.mmh_thresholds = data.get("mmh_thresholds", {})
            print("[dtw_learner] Loaded existing DTW model.")
            return True
        except Exception:
            return False

class DTWLearningSystem:
    """
    Drop-in replacement for GestureLearningSystem using DTW algorithm.
    """
    _DIR_VECTORS = {
        "right": ( 1.0,  0.0),
        "left":  (-1.0,  0.0),
        "up":    ( 0.0, -1.0),
        "down":  ( 0.0,  1.0),
    }
    
    def __init__(self, username: str = "", profile: Optional[GestureProfile] = None):
        self._username = username
        data_dir = _user_data_dir(username)
        self.buffer = GestureBuffer(maxlen=100) # Slightly larger buffer for continuous DTW
        self.extractor = OrientationIndependentExtractor()
        self._session_id = f"dtw_sess_{int(time.time())}"
        
        self.dataset = DTWDataset(data_dir)
        self.model = DTWModel(data_dir)
        self.model.load()
        
        self._profile = profile or PROFILE_STANDARD
        self._pred_history: deque = deque(maxlen=self._profile.smoothing_frames)
        self._last_rec = 0.0
        self._last_rec_flash = 0.0
        
        self.recordings: List[Dict] = []
        self._class_counts: Dict[str, int] = {d: 0 for d in IntentLabeler.DIRECTIONS}
        
    def set_profile(self, profile: GestureProfile) -> None:
        self._profile = profile
        self._pred_history = deque(maxlen=profile.smoothing_frames)

    def start_validation(self) -> None:
        pass # Validation via GestureValidator to be implemented or hooked up later
        
    def update(self, gs):
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
        
    def try_record(self, gs, blade_xy, fruits_xy, mode="standard"):
        if not fruits_xy: return False
        
        now = time.monotonic()
        if now - self._last_rec < self._profile.cooldown_secs:
            return False
            
        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)
        if gyro_mag < self._profile.motion_mag_min:
            return False
            
        window = self.buffer.snapshot()
        if len(window) < 10: return False
        
        # DTW doesn't need to perfectly center, but we grab a window of recent history
        # when motion is high.
        curve = self.extractor.extract(window)
        
        label = IntentLabeler.label(
            blade_xy, fruits_xy,
            ambiguity_margin=self._profile.ambiguity_margin
        )
        if label is None: return False
        
        # Serialize raw window for second stage classifier later
        raw_serial = []
        for s in window:
            raw_serial.append({
                "t": s.t, "gx": s.gx, "gy": s.gy, "gz": s.gz, 
                "ax": s.ax, "ay": s.ay, "az": s.az,
                "euler_roll": s.euler_roll, "euler_pitch": s.euler_pitch
            })
            
        self.recordings.append({
            "schema_version": SCHEMA_VERSION_DTW,
            "algorithm": "DTW",
            "curve": curve,
            "raw_window": raw_serial,
            "label": label,
            "time": now,
            "session_id": self._session_id,
            "mode": mode
        })
        self._class_counts[label] = self._class_counts.get(label, 0) + 1
        self._last_rec = now
        self._last_rec_flash = now
        return True
        
    def predict(self, gs) -> Tuple[Optional[str], float]:
        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)
        
        if gyro_mag < self._profile.dead_zone:
            self._pred_history.clear()
            return None, 0.0
            
        if not self.model.ready:
            return None, 0.0
            
        window = self.buffer.snapshot()
        if len(window) < 10:
            return None, 0.0
            
        curve = self.extractor.extract(window)
        
        # Run Auto-segmentation against all templates
        matches = []
        for class_label, template in self.model.templates.items():
            dist, start_idx, end_idx = DTWEngine.auto_segment(curve, template)
            threshold = self.model.mmh_thresholds.get(class_label, 1000.0)
            
            if dist < threshold:
                matches.append((class_label, dist))
                
        if not matches:
            return None, 0.0
            
        matches.sort(key=lambda x: x[1])
        candidates = [m[0] for m in matches if m[1] < matches[0][1] * 1.5]
        
        from shared.dtw_learner import SecondStageClassifier
        final_dir = SecondStageClassifier.resolve_direction(window, candidates)
        
        self._pred_history.append(final_dir)
        counts = {}
        for p in self._pred_history: counts[p] = counts.get(p, 0) + 1
        best_dir = max(counts, key=lambda d: counts[d])
        majority_frac = counts[best_dir] / len(self._pred_history)
        
        # Convert DTW distance back to a pseudo-confidence (0.0 to 1.0)
        # Distance is typically between 0 and threshold.
        # So confidence = 1.0 - (dist / threshold)
        best_dist = matches[0][1]
        threshold = self.model.mmh_thresholds.get(best_dir, 1000.0)
        confidence = max(0.0, 1.0 - (best_dist / max(1.0, threshold)))
        
        if majority_frac < 0.6:
            return None, confidence
            
        return best_dir, confidence

    def get_cursor_delta(self, gs, scale_x: float, scale_y: float, dt: float) -> Tuple[float, float]:
        gyro_mag = math.sqrt(gs.abs_gx**2 + gs.abs_gy**2 + gs.abs_gz**2)
        gz = gs.abs_gz if abs(gs.abs_gz) >= self._profile.dead_zone else 0.0
        gy = gs.abs_gy if abs(gs.abs_gy) >= self._profile.dead_zone else 0.0
        
        if gyro_mag < self._profile.dead_zone:
            self._pred_history.clear()
            return 0.0, 0.0
            
        if not self.model.ready:
            return -gz * scale_x * dt, gy * scale_y * dt
            
        window = self.buffer.snapshot()
        if len(window) < 10:
            return -gz * scale_x * dt, gy * scale_y * dt
            
        curve = self.extractor.extract(window)
        
        # Run Auto-segmentation against all templates
        matches = []
        for class_label, template in self.model.templates.items():
            dist, start_idx, end_idx = DTWEngine.auto_segment(curve, template)
            threshold = self.model.mmh_thresholds.get(class_label, 1000.0)
            
            # Use MMH for classification
            if dist < threshold:
                matches.append((class_label, dist))
                
        if not matches:
            return -gz * scale_x * dt * 0.5, gy * scale_y * dt * 0.5
            
        # Find best match
        matches.sort(key=lambda x: x[1])
        best_class = matches[0][0]
        
        # Second stage classifier for reversible gestures
        # Pass candidates that fall within threshold
        candidates = [m[0] for m in matches if m[1] < matches[0][1] * 1.5]
        final_dir = SecondStageClassifier.resolve_direction(window, candidates)
        
        self._pred_history.append(final_dir)
        counts = {}
        for p in self._pred_history: counts[p] = counts.get(p, 0) + 1
        best_dir = max(counts, key=lambda d: counts[d])
        majority_frac = counts[best_dir] / len(self._pred_history)
        
        if majority_frac < 0.6:
            return -gz * scale_x * dt * 0.3, gy * scale_y * dt * 0.3
            
        dx_u, dy_u = self._DIR_VECTORS.get(best_dir, (0.0, 0.0))
        speed = min(gyro_mag, 300.0) * (scale_x + scale_y) * 0.5 * dt * self._profile.max_speed_scale
        return dx_u * speed, dy_u * speed
        
    def save_and_train(self) -> bool:
        if self.recordings:
            self.dataset.save_session(self.recordings)
            self.recordings.clear()
            
        X, y, raw_windows = self.dataset.load_all()
        if len(X) >= MIN_TRAIN_SAMPLES:
            ok = self.model.train(X, y)
            if ok:
                print(f"[dtw_learner] DTW Model retrained on {len(X)} samples.")
            return ok
        print(f"[dtw_learner] Not enough samples ({len(X)}/{MIN_TRAIN_SAMPLES}).")
        return False
        
    # UI Helpers
    @property
    def rec_flash_active(self) -> bool:
        return time.monotonic() - self._last_rec_flash < 0.4

    @property
    def total_recordings(self) -> int:
        return len(self.recordings)

    @property
    def model_ready(self) -> bool:
        return self.model.ready

    @property
    def sklearn_available(self) -> bool:
        return True # DTW doesn't require sklearn

    @property
    def class_balance_ok(self) -> bool:
        # Simplified balance check
        counts = [v for v in self._class_counts.values() if v > 0]
        if len(counts) < 2: return True
        return max(counts) / min(counts) < 3.0

    @property
    def class_counts(self) -> Dict[str, int]:
        return dict(self._class_counts)

    @property
    def saved_sample_count(self) -> int:
        X, y, _ = self.dataset.load_all()
        return len(X)
        
    @property
    def validation_running(self) -> bool: return False
    
    @property
    def validation_result(self): return None
