"""
gestures/ml_detector.py — Two-stage MLDetector plug-in (roadmap §7.8, Phase 7).

Integrates with `GestureInterpreter` as both:
  • a `Detector` plug-in emitting `GestureEvent(..., source="ml")` when a
    trained `GestureModel` (and optional DTW template engine) predicts an
    intentional gesture above the confidence threshold, and
  • a Stage-1 involuntary gate (`is_involuntary(buffer)`) that suppresses
    rule-based events when the Stage-1 classifier flags a spasm.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Sequence

from shared.gesture_learner import (
    EVENT_FRAMES, GestureModel, features as extract_features,
)
from shared.gestures.types import Frame, Gesture, GestureEvent

_DIR_TO_FLICK: Dict[str, Gesture] = {
    "up": Gesture.FLICK_UP,
    "down": Gesture.FLICK_DOWN,
    "left": Gesture.FLICK_LEFT,
    "right": Gesture.FLICK_RIGHT,
}


class MLDetector:
    """Two-stage RandomForest (+ optional DTW) detector and involuntary gate."""

    def __init__(
        self,
        model: GestureModel,
        window_size: int = EVENT_FRAMES,
        rest_gate_dps: float = 15.0,
        cooldown_s: float = 0.6,
        smoothing_frames: int = 4,
        dtw_engine=None,
        emit_slice: bool = True,
        name: str = "ml",
    ):
        self.name = name
        self.model = model
        self.window_size = window_size
        self.rest_gate_dps = rest_gate_dps
        self.cooldown_s = cooldown_s
        self.smoothing_frames = smoothing_frames
        self.dtw_engine = dtw_engine
        self.emit_slice = emit_slice
        self.reset()

    def reset(self) -> None:
        self._buf: deque = deque(maxlen=max(self.window_size, 60))
        self._pred_hist: deque = deque(maxlen=self.smoothing_frames)
        self._last_fire: float = -1e9
        self.last_stage1_label: str = "rest"
        self.last_stage1_conf: float = 1.0

    def is_involuntary(self, buffer: Optional[Sequence[Frame]] = None) -> bool:
        """Return True if the Stage-1 classifier flags the recent window as involuntary."""
        win = list(buffer)[-self.window_size:] if buffer else list(self._buf)[-self.window_size:]
        if len(win) < 6 or not self.model.stage1_ready:
            return False
        feat = extract_features(win)
        if feat is None:
            return False
        lbl, conf = self.model.predict_stage1(feat)
        self.last_stage1_label, self.last_stage1_conf = lbl, conf
        return lbl == "involuntary" and conf >= self.model.confidence_threshold

    def update(self, f: Frame) -> List[GestureEvent]:
        self._buf.append(f)
        if not f.calibrated or len(self._buf) < 6:
            return []
        if f.av_magnitude < self.rest_gate_dps:
            self._pred_hist.clear()
            self.last_stage1_label = "rest"
            return []
        if not self.model.ready or f.t - self._last_fire <= self.cooldown_s:
            return []

        win = list(self._buf)[-self.window_size:]
        feat = extract_features(win)
        if feat is None:
            return []

        # Stage 1 gate
        if self.model.stage1_ready:
            s1_lbl, s1_conf = self.model.predict_stage1(feat)
            self.last_stage1_label, self.last_stage1_conf = s1_lbl, s1_conf
            if s1_lbl != "intentional" or s1_conf < self.model.confidence_threshold:
                return []

        # Stage 2: RandomForest (with optional DTW fallback)
        direction, conf = self.model.predict_with_confidence(feat)
        if direction is None and self.dtw_engine is not None and getattr(self.dtw_engine, "model_ready", False):
            direction, conf = self.dtw_engine.predict(f)
        if direction is None:
            return []

        self._pred_hist.append(direction)
        counts: Dict[str, int] = {}
        for d in self._pred_hist:
            counts[d] = counts.get(d, 0) + 1
        best = max(counts, key=lambda d: counts[d])
        if counts[best] / len(self._pred_hist) < 0.6:
            return []

        self._last_fire = f.t
        self._pred_hist.clear()
        if self.emit_slice:
            return [GestureEvent(
                Gesture.SLICE, strength=min(1.0, f.av_magnitude / 300.0),
                confidence=conf, direction=best, source="ml", t=f.t, detector=self.name,
            )]
        g = _DIR_TO_FLICK.get(best, Gesture.ANY_MOVE)
        return [GestureEvent(
            g, strength=min(1.0, f.av_magnitude / 300.0),
            confidence=conf, direction=best, source="ml", t=f.t, detector=self.name,
        )]

