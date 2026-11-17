"""
recorder.py — JSONL IMU sample recorder and loader (roadmap Phase 1).

Format: one JSON object per line:
  {"t": 0.010, "ax": 0.0, "ay": 0.0, "az": 1.0,
   "gx": 0.0, "gy": 0.0, "gz": 0.0,
   "hw_fusion_valid": true, "hw_qw": 1.0, "hw_qx": 0.0, "hw_qy": 0.0, "hw_qz": 0.0,
   "hw_heading": 0.0, "hw_pitch": 0.0, "hw_roll": 0.0}
"""

from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, TextIO, Union

from shared.sensor import IMUSample


def sample_to_dict(s: IMUSample, t0: Optional[float] = None) -> dict:
    t = (s.timestamp - t0) if t0 is not None else s.timestamp
    return {
        "t": round(float(t), 6),
        "ax": round(float(s.ax), 6),
        "ay": round(float(s.ay), 6),
        "az": round(float(s.az), 6),
        "gx": round(float(s.gx), 4),
        "gy": round(float(s.gy), 4),
        "gz": round(float(s.gz), 4),
        "hw_heading": round(float(s.hw_heading), 4),
        "hw_pitch": round(float(s.hw_pitch), 4),
        "hw_roll": round(float(s.hw_roll), 4),
        "hw_fusion_valid": bool(s.hw_fusion_valid),
        "hw_qw": round(float(getattr(s, "hw_qw", 0.0)), 6),
        "hw_qx": round(float(getattr(s, "hw_qx", 0.0)), 6),
        "hw_qy": round(float(getattr(s, "hw_qy", 0.0)), 6),
        "hw_qz": round(float(getattr(s, "hw_qz", 0.0)), 6),
    }


def dict_to_sample(d: dict) -> IMUSample:
    return IMUSample(
        timestamp=float(d.get("t", d.get("timestamp", 0.0))),
        ax=float(d.get("ax", 0.0)),
        ay=float(d.get("ay", 0.0)),
        az=float(d.get("az", 1.0)),
        gx=float(d.get("gx", 0.0)),
        gy=float(d.get("gy", 0.0)),
        gz=float(d.get("gz", 0.0)),
        hw_heading=float(d.get("hw_heading", 0.0)),
        hw_pitch=float(d.get("hw_pitch", 0.0)),
        hw_roll=float(d.get("hw_roll", 0.0)),
        hw_fusion_valid=bool(d.get("hw_fusion_valid", False)),
        hw_qw=float(d.get("hw_qw", 0.0)),
        hw_qx=float(d.get("hw_qx", 0.0)),
        hw_qy=float(d.get("hw_qy", 0.0)),
        hw_qz=float(d.get("hw_qz", 0.0)),
    )


def write_samples(path: Union[str, Path], samples: Iterable[IMUSample],
                  relative_time: bool = True) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t0: Optional[float] = None
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for s in samples:
            if relative_time and t0 is None:
                t0 = s.timestamp
            fh.write(json.dumps(sample_to_dict(s, t0)) + "\n")
            count += 1
    return count


def load_samples(path: Union[str, Path]) -> List[IMUSample]:
    path = Path(path)
    out: List[IMUSample] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(dict_to_sample(json.loads(line)))
    return out


class SampleRecorder:
    """Thread-safe streaming JSONL writer suitable for `sensor.set_sample_callback`."""

    def __init__(self, path: Union[str, Path], relative_time: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.relative_time = relative_time
        self._fh: Optional[TextIO] = self.path.open("w", encoding="utf-8")
        self._lock = threading.Lock()
        self._t0: Optional[float] = None
        self.count: int = 0

    def __call__(self, sample: IMUSample) -> None:
        self.write(sample)

    def write(self, sample: IMUSample) -> None:
        with self._lock:
            if self._fh is None:
                return
            if self.relative_time and self._t0 is None:
                self._t0 = sample.timestamp
            self._fh.write(json.dumps(sample_to_dict(sample, self._t0)) + "\n")
            self.count += 1
            if self.count % 50 == 0:
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "SampleRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


DUAL_DATASET_COLUMNS = [
    "timestamp",
    "dual_sensor_active",
    "pos_x",
    "pos_y",
    "pos_z",
    "wrist_qw",
    "wrist_qx",
    "wrist_qy",
    "wrist_qz",
    "upper_qw",
    "upper_qx",
    "upper_qy",
    "upper_qz",
    "lin_acc_x",
    "lin_acc_y",
    "lin_acc_z",
    "gesture_label",
]


class DualArmDatasetLogger:
    """Thread-safe synchronized CSV dataset logger for single or twin-sensor 3D arm data."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: Optional[TextIO] = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(DUAL_DATASET_COLUMNS)
        self._lock = threading.Lock()
        self.count: int = 0

    def log(
        self,
        timestamp: float,
        dual_sensor_active: bool,
        pos_xyz: Sequence[float] = (0.0, 0.0, 0.0),
        wrist_q: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        upper_q: Optional[Sequence[float]] = None,
        lin_acc: Sequence[float] = (0.0, 0.0, 0.0),
        gesture_label: str = "",
    ) -> None:
        uq = upper_q if upper_q is not None else (0.0, 0.0, 0.0, 0.0)
        row = [
            round(float(timestamp), 6),
            bool(dual_sensor_active),
            round(float(pos_xyz[0]), 4),
            round(float(pos_xyz[1]), 4),
            round(float(pos_xyz[2]), 4),
            round(float(wrist_q[0]), 6),
            round(float(wrist_q[1]), 6),
            round(float(wrist_q[2]), 6),
            round(float(wrist_q[3]), 6),
            round(float(uq[0]), 6),
            round(float(uq[1]), 6),
            round(float(uq[2]), 6),
            round(float(uq[3]), 6),
            round(float(lin_acc[0]), 6),
            round(float(lin_acc[1]), 6),
            round(float(lin_acc[2]), 6),
            str(gesture_label),
        ]
        with self._lock:
            if self._fh is None:
                return
            self._writer.writerow(row)
            self.count += 1
            if self.count % 50 == 0:
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "DualArmDatasetLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

