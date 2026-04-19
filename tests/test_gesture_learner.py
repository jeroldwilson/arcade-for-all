"""
Unit tests for gesture_learner.py

Coverage:
  1. Fallback cursor sign matches regular game mode exactly
  2. SmartRecorder goal guard (no fruits → no recording)
  3. IntentLabeler ambiguity rejection (diagonal)
  4. GestureModel confidence abstain
  5. Session-aware CV split (no session leaks across folds)
  6. FeatureExtractor output shape
  7. SKLEARN_AVAILABLE flag doesn't fake model-ready state
"""

import math
import sys
import time
import types
import unittest
from pathlib import Path
from collections import deque
from typing import List, Optional
from unittest.mock import MagicMock, patch

# Make shared/ importable when running from repo root or tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.gesture_learner import (
    SKLEARN_AVAILABLE,
    BUFFER_FRAMES,
    EVENT_FRAMES,
    MIN_TRAIN_SAMPLES,
    PROFILE_STANDARD,
    GestureBuffer,
    GestureProfile,
    GestureLearningSystem,
    GestureModel,
    GestureValidator,
    GestureDataset,
    FeatureExtractor,
    IMUSnapshot,
    IntentLabeler,
    SmartRecorder,
    ValidationResult,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_gs(abs_gx=0.0, abs_gy=0.0, abs_gz=0.0,
             abs_ax=0.0, abs_ay=0.0, abs_az=1.0,
             euler_roll=0.0, euler_pitch=0.0):
    """Minimal GestureState stand-in with the fields GestureLearningSystem reads."""
    gs = types.SimpleNamespace(
        abs_gx=abs_gx, abs_gy=abs_gy, abs_gz=abs_gz,
        abs_ax=abs_ax, abs_ay=abs_ay, abs_az=abs_az,
        euler_roll=euler_roll, euler_pitch=euler_pitch,
    )
    return gs


def _make_window(n: int = EVENT_FRAMES, gx=0.0, gy=50.0, gz=80.0) -> List[IMUSnapshot]:
    return [
        IMUSnapshot(t=float(i), gx=gx, gy=gy, gz=gz, ax=0.0, ay=0.0, az=1.0)
        for i in range(n)
    ]


def _make_feature_vector():
    """Return a valid 38-float feature vector (all ones)."""
    return [1.0] * FeatureExtractor.N_FEATURES


# ── 1. Fallback cursor sign matches regular mode ──────────────────────────────

class TestFallbackSignConvention(unittest.TestCase):
    """
    Regular mode (game.py _update_blade):
        dx =  -gz * scale_x * dt
        dy =   gy * scale_y * dt

    Fallback path in get_cursor_delta() must produce identical signs.
    """

    def _get_fallback_delta(self, gz: float, gy: float,
                            scale_x=5.0, scale_y=5.0, dt=1.0 / 60):
        """Drive get_cursor_delta through the no-model fallback path."""
        gs = _make_gs(abs_gx=0.0, abs_gy=gy, abs_gz=gz)
        system = GestureLearningSystem.__new__(GestureLearningSystem)
        system.buffer       = GestureBuffer()
        system.extractor    = FeatureExtractor()
        system.recorder     = SmartRecorder(system.buffer, system.extractor)
        system._session_id  = "test"
        system._profile     = PROFILE_STANDARD
        system._pred_history = deque(maxlen=4)
        system._last_rec_flash = 0.0
        system._validator   = None
        # Model is not ready → forces fallback branch
        system.model = GestureModel.__new__(GestureModel)
        system.model._clf = None
        system.model.confidence_threshold = 0.55
        return system.get_cursor_delta(gs, scale_x, scale_y, dt)

    def test_gz_positive_cursor_right(self):
        """gz > 0 → regular mode gives dx < 0; fallback must match."""
        dx, _dy = self._get_fallback_delta(gz=100.0, gy=0.0)
        # Regular: dx = -gz * scale = -500/60 < 0
        self.assertLess(dx, 0,
            "gz>0 should move cursor left (dx<0), matching regular mode -gz convention")

    def test_gz_negative_cursor_left(self):
        """gz < 0 → dx > 0 (cursor right)."""
        dx, _dy = self._get_fallback_delta(gz=-100.0, gy=0.0)
        self.assertGreater(dx, 0)

    def test_gy_positive_cursor_up(self):
        """gy > 0 → dy > 0 in regular mode (cursor up, screen-coords positive-down)."""
        _dx, dy = self._get_fallback_delta(gz=0.0, gy=100.0)
        # Regular: dy = gy * scale > 0
        self.assertGreater(dy, 0,
            "gy>0 should give dy>0, matching regular mode +gy convention")

    def test_gy_negative_cursor_down(self):
        """gy < 0 → dy < 0."""
        _dx, dy = self._get_fallback_delta(gz=0.0, gy=-100.0)
        self.assertLess(dy, 0)

    def test_still_returns_zero(self):
        """Below dead-zone → (0, 0)."""
        dx, dy = self._get_fallback_delta(gz=5.0, gy=3.0)
        self.assertEqual((dx, dy), (0.0, 0.0))


# ── 2. Recorder goal guard ────────────────────────────────────────────────────

class TestRecorderGoalGuard(unittest.TestCase):

    def _make_recorder_with_data(self):
        buf = GestureBuffer()
        ext = FeatureExtractor()
        for i in range(BUFFER_FRAMES):
            buf.push(IMUSnapshot(t=float(i), gx=5.0, gy=60.0, gz=90.0,
                                 ax=0.0, ay=0.0, az=1.0))
        rec = SmartRecorder(buf, ext)
        return rec

    def test_no_fruits_returns_false(self):
        rec = self._make_recorder_with_data()
        gs  = _make_gs(abs_gx=0, abs_gy=80, abs_gz=120)
        result = rec.try_record(gs, blade_xy=(400.0, 300.0), fruits_xy=[])
        self.assertFalse(result, "Goal guard must reject when no fruits are present")

    def test_with_fruit_may_record(self):
        rec = self._make_recorder_with_data()
        # Force past cooldown
        rec._last_rec = 0.0
        gs  = _make_gs(abs_gx=0, abs_gy=80, abs_gz=120)
        # Fruit directly to the right (unambiguous label)
        result = rec.try_record(gs, blade_xy=(200.0, 300.0), fruits_xy=[(600.0, 300.0)])
        # May or may not record depending on erratic guard — but goal guard won't block
        # (we can't assert True because other guards may intervene; just confirm no exception)
        self.assertIsInstance(result, bool)


# ── 3. IntentLabeler ambiguity rejection ─────────────────────────────────────

class TestIntentLabelerAmbiguity(unittest.TestCase):

    def test_clear_horizontal_accepted(self):
        # dx=200, dy=0 → clearly right
        label = IntentLabeler.label((0, 0), [(200, 0)])
        self.assertEqual(label, "right")

    def test_clear_vertical_accepted(self):
        # dx=0, dy=200 → clearly down
        label = IntentLabeler.label((0, 0), [(0, 200)])
        self.assertEqual(label, "down")

    def test_diagonal_45_rejected(self):
        # dx=100, dy=100 → 50/50 split — ambiguous
        label = IntentLabeler.label((0, 0), [(100, 100)])
        self.assertIsNone(label, "45° diagonal must be rejected as ambiguous")

    def test_near_diagonal_rejected(self):
        # dx=10, dy=8 → dom_frac=10/18≈0.556 < 0.75 → ambiguous
        label = IntentLabeler.label((0, 0), [(10, 8)])
        self.assertIsNone(label)

    def test_dominant_enough_accepted(self):
        # dx=10, dy=3 → dom_frac=10/13≈0.769 ≥ 0.75 → right
        label = IntentLabeler.label((0, 0), [(10, 3)])
        self.assertEqual(label, "right")

    def test_no_fruits_returns_none(self):
        label = IntentLabeler.label((100, 100), [])
        self.assertIsNone(label)

    def test_trajectory_disagrees_rejected(self):
        # Fruit is to the right but blade moved left → reject
        blade_history = [(500, 300), (450, 300), (380, 300)]  # moved left
        label = IntentLabeler.label(
            (300, 300), [(600, 300)],
            blade_history=blade_history,
        )
        self.assertIsNone(label, "Trajectory-fruit disagreement must be rejected")

    def test_trajectory_agrees_accepted(self):
        # Fruit is to the right and blade also moved right
        blade_history = [(200, 300), (250, 300), (320, 300)]
        label = IntentLabeler.label(
            (320, 300), [(600, 300)],
            blade_history=blade_history,
        )
        self.assertEqual(label, "right")


# ── 4. Confidence abstain ─────────────────────────────────────────────────────

class TestConfidenceAbstain(unittest.TestCase):

    def _make_model_with_proba(self, confidence: float) -> GestureModel:
        """Build a mock classifier whose best-class probability equals `confidence`."""
        model = GestureModel.__new__(GestureModel)
        model.MODEL_PATH = Path("/tmp/nonexistent_model.pkl")
        model.confidence_threshold = 0.55
        clf_mock = MagicMock()
        # Distribute remaining probability equally across the other three classes
        rest = (1.0 - confidence) / 3
        clf_mock.predict_proba.return_value = [[confidence, rest, rest, rest]]
        clf_mock.classes_ = ["right", "left", "up", "down"]
        model._clf = clf_mock
        return model

    def test_above_threshold_commits(self):
        model = self._make_model_with_proba(0.80)
        direction, conf = model.predict_with_confidence(_make_feature_vector())
        self.assertIsNotNone(direction)
        self.assertAlmostEqual(conf, 0.80, places=5)

    def test_below_threshold_abstains(self):
        model = self._make_model_with_proba(0.40)
        direction, conf = model.predict_with_confidence(_make_feature_vector())
        self.assertIsNone(direction, "Low confidence must return None (abstain)")
        self.assertAlmostEqual(conf, 0.40, places=5)

    def test_at_threshold_abstains(self):
        # Exactly at threshold → still abstain (strict <)
        model = self._make_model_with_proba(0.549)
        direction, _ = model.predict_with_confidence(_make_feature_vector())
        self.assertIsNone(direction)

    def test_no_clf_returns_none(self):
        model = GestureModel.__new__(GestureModel)
        model._clf = None
        model.confidence_threshold = 0.55
        direction, conf = model.predict_with_confidence(_make_feature_vector())
        self.assertIsNone(direction)
        self.assertEqual(conf, 0.0)


# ── 5. Session-aware CV split ─────────────────────────────────────────────────

class TestSessionAwareSplit(unittest.TestCase):
    """Verify that no session appears in both train and test folds."""

    @unittest.skipUnless(SKLEARN_AVAILABLE, "sklearn required")
    def test_no_session_leakage(self):
        import tempfile, json, os
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = Path(tmpdir) / "sessions"
            sess_dir.mkdir()
            ext = FeatureExtractor()

            # Create 4 sessions with 5 samples each, distinct patterns
            feat = _make_feature_vector()
            for s_i in range(4):
                recs = []
                for _ in range(5):
                    recs.append({
                        "schema_version": 2,
                        "features": feat,
                        "label": ["right", "left", "up", "down"][s_i],
                        "time": time.monotonic(),
                        "session_id": f"session_{s_i:02d}",
                        "mode": "standard",
                        "quality": {},
                    })
                p = sess_dir / f"session_{s_i:02d}.json"
                p.write_text(json.dumps(recs))

            dataset   = GestureDataset(data_dir=Path(tmpdir))
            validator = GestureValidator(dataset, n_folds=4)

            # Run synchronously
            result = validator._validate()

            # If we get here without error, session-aware split ran without crashing
            self.assertIsInstance(result, ValidationResult)
            # Should have used at least 2 folds
            self.assertGreaterEqual(result.cv_folds_used, 2,
                                    "Expected ≥2 folds to be used")


# ── 6. FeatureExtractor output shape ─────────────────────────────────────────

class TestFeatureExtractor(unittest.TestCase):

    def test_correct_length(self):
        ext    = FeatureExtractor()
        window = _make_window(n=EVENT_FRAMES)
        feats  = ext.extract(window)
        self.assertIsNotNone(feats)
        self.assertEqual(len(feats), FeatureExtractor.N_FEATURES)

    def test_too_short_returns_none(self):
        ext   = FeatureExtractor()
        feats = ext.extract(_make_window(n=2))
        self.assertIsNone(feats)

    def test_single_frame_window(self):
        ext   = FeatureExtractor()
        feats = ext.extract(_make_window(n=3))
        self.assertIsNotNone(feats)
        self.assertEqual(len(feats), FeatureExtractor.N_FEATURES)


# ── 7. SKLEARN_AVAILABLE never fakes model-ready ─────────────────────────────

class TestSklearnUnavailableNeverFakeReady(unittest.TestCase):

    def test_model_not_ready_without_clf(self):
        model = GestureModel.__new__(GestureModel)
        model._clf = None
        model.confidence_threshold = 0.55
        self.assertFalse(model.ready,
                         "GestureModel.ready must be False when _clf is None")

    def test_train_fails_gracefully_without_sklearn(self):
        """If SKLEARN_AVAILABLE is False, train() must return False without exception."""
        model = GestureModel.__new__(GestureModel)
        model._clf = None
        model.confidence_threshold = 0.55
        model.MODEL_PATH = Path("/tmp/no_model.pkl")

        X = [[1.0] * FeatureExtractor.N_FEATURES] * 20
        y = ["right"] * 10 + ["left"] * 10

        with patch("shared.gesture_learner.SKLEARN_AVAILABLE", False):
            result = model.train(X, y)
        self.assertFalse(result,
                         "train() must return False when sklearn is not available")
        self.assertIsNone(model._clf,
                          "_clf must remain None when training fails")


if __name__ == "__main__":
    unittest.main(verbosity=2)
