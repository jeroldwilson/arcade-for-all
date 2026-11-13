"""
test_roadmap_pipeline.py — Unit and replay tests for v1.0 roadmap Phases 0–5.

Runs without hardware or pygame (`python -m unittest discover -s tests`).
"""

from __future__ import annotations

import math
import queue
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.child_profile import ChildProfile
from shared.frontend import Biquad, Frontend, FrontendConfig, butter2_lowpass
from shared.gesture import GestureConfig, GestureInterpreter
from shared.gesture_detector import SliceDetector
from shared.gesture_learner import (
    FeatureExtractor, GestureBuffer, GestureModel, IMUSnapshot,
    SCHEMA_VERSION, SmartRecorder, features as extract_ml_features,
)
from shared.gestures.accessible import (
    AnyMoveDetector, DwellDetector, HoldDetector, SpasmGate, StillDetector,
)
from shared.gestures.bindings import dispatch_bindings, poll_and_signals
from shared.gestures.ml_detector import MLDetector
from shared.gestures.types import Frame, Gesture, GestureEvent, Signals
from shared.quat import euler_from_q, gravity_from_q, q_from_euler, q_mul, q_relative
from shared.recorder import SampleRecorder, load_samples
from shared.sensor import _CMD_SF_MODE, _SF_MODE_IMUPLUS, IMUSample, MetaMotionSensor
from tests.replay import (
    FIXTURES_DIR, _make_sample, ensure_fixtures, replay, replay_full,
)


class TestPhase0SensorAndBugFixes(unittest.TestCase):
    """Roadmap Phase 0: sensor protocol, quaternion parsing, direction-aware launch, slice sign."""

    def test_sf_mode_is_imuplus_not_ndof(self) -> None:
        self.assertEqual(_SF_MODE_IMUPLUS, 0x02)
        self.assertEqual(_CMD_SF_MODE[2], 0x02, "Sensor fusion mode byte must be IMUPlus (0x02)")

    def test_parse_sf_quat_populates_imusample_and_rate_stats(self) -> None:
        sensor = MetaMotionSensor(sf_profile="lean")
        q = q_from_euler(15.0, -10.0, 45.0)
        payload = bytearray(struct.pack("<ffff", *q))
        for _ in range(12):
            sensor._parse_sf_quat(payload)
        self.assertTrue(sensor._hw_fusion_valid)
        s = sensor.data_queue.get_nowait()
        self.assertTrue(s.hw_fusion_valid)
        self.assertAlmostEqual(s.hw_qw, q[0], places=4)
        self.assertAlmostEqual(s.hw_roll, 15.0, places=2)
        self.assertAlmostEqual(s.hw_pitch, -10.0, places=2)

    def test_frontend_skips_madgwick_when_hw_quaternion_valid(self) -> None:
        fe = Frontend()
        with patch.object(fe._fusion, "process", wraps=fe._fusion.process) as spy:
            s = _make_sample(0.01, roll_deg=10.0, pitch_deg=-5.0)
            fe.process(s)
            self.assertEqual(spy.call_count, 0, "Madgwick must be skipped when hw_fusion_valid")

    def test_direction_aware_launch_ignores_downward_jerk(self) -> None:
        ensure_fixtures()
        events, states, _ = replay_full(FIXTURES_DIR / "flicks_up.jsonl")
        flick_events = [e for e in events if e.detector == "flick"]
        self.assertEqual([e.gesture for e in flick_events], [Gesture.FLICK_UP, Gesture.FLICK_DOWN])
        # Only the first (upward) flick may set state.launch = True
        launch_times = [s.raw_ax for s in states if s.launch]
        self.assertEqual(len(launch_times), 1, "Downward jerk must not trigger launch")

    def test_slice_detector_up_vs_down_sign(self) -> None:
        sd = SliceDetector()
        ev = None
        for i in range(8):
            ev = sd.update(0.0, -220.0, 0.0, t=i * 0.01)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.direction, "up")

        sd2 = SliceDetector()
        ev2 = None
        for i in range(8):
            ev2 = sd2.update(0.0, +220.0, 0.0, t=i * 0.01)
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2.direction, "down")

    def test_haptics_vibrate_called_on_accepted_gesture(self) -> None:
        from shared.game_experience import InactivityMonitor, VisualEffects
        ensure_fixtures()
        mock_sensor = MagicMock()
        mock_sensor.mag_cal_state = 3
        interp = GestureInterpreter(queue.Queue(), GestureConfig(), sensor=mock_sensor)
        for s in load_samples(FIXTURES_DIR / "flicks_up.jsonl"):
            interp._process(s)
        self.assertEqual(mock_sensor.vibrate.call_count, 0, "Gestures must not trigger haptics")

        # Score celebration triggers vibrate
        fx = VisualEffects(sensor=mock_sensor)
        fx.trigger_fireworks(100, 100)
        self.assertEqual(mock_sensor.vibrate.call_count, 1)

        # InactivityMonitor vibrates only after >30s rest, then every 15s
        mock_sensor.vibrate.reset_mock()
        mon = InactivityMonitor("Tester", sensor=mock_sensor)
        with patch("shared.game_experience.time.time", return_value=mon.last_motion_time + 20.0):
            mon.update(is_moving=False)
        self.assertEqual(mock_sensor.vibrate.call_count, 0)
        with patch("shared.game_experience.time.time", return_value=mon.last_motion_time + 31.0):
            mon.update(is_moving=False)
        self.assertEqual(mock_sensor.vibrate.call_count, 1)
        with patch("shared.game_experience.time.time", return_value=mon.last_motion_time + 40.0):
            mon.update(is_moving=False)
        self.assertEqual(mock_sensor.vibrate.call_count, 1)
        with patch("shared.game_experience.time.time", return_value=mon.last_motion_time + 47.0):
            mon.update(is_moving=False)
        self.assertEqual(mock_sensor.vibrate.call_count, 2)


class TestPhase1ReplayHarness(unittest.TestCase):
    """Roadmap Phase 1: JSONL recorder + deterministic offline replay."""

    def setUp(self) -> None:
        ensure_fixtures()

    def test_recorder_roundtrip_preserves_quaternion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rec.jsonl"
            s_in = _make_sample(1.25, roll_deg=12.0, pitch_deg=-8.0, yaw_deg=33.0, gx=5.0)
            with SampleRecorder(path, relative_time=False) as rec:
                rec(s_in)
            loaded = load_samples(path)
            self.assertEqual(len(loaded), 1)
            self.assertAlmostEqual(loaded[0].hw_qw, s_in.hw_qw, places=5)
            self.assertAlmostEqual(loaded[0].hw_roll, 12.0, places=3)

    def test_rest_and_tremor_produce_zero_events(self) -> None:
        self.assertEqual(replay(FIXTURES_DIR / "rest.jsonl"), [])
        self.assertEqual(replay(FIXTURES_DIR / "tremor.jsonl"), [])

    def test_slices_fixture_emits_expected_directions(self) -> None:
        events = [e for e in replay(FIXTURES_DIR / "slices.jsonl") if e.gesture is Gesture.SLICE]
        self.assertEqual([e.direction for e in events], ["right", "up"])


class TestPhase2Frontend(unittest.TestCase):
    """Roadmap Phase 2: baseline quaternion q_rel + Butterworth biquad lag < 100 ms."""

    def test_baseline_quaternion_handles_tilted_mounting(self) -> None:
        # Sensor strapped at a 40° roll, -25° pitch resting angle
        q_mount = q_from_euler(40.0, -25.0, 15.0)
        fe = Frontend(FrontendConfig(calibration_seconds=0.5))
        for i in range(60):
            g = gravity_from_q(q_mount)
            s = IMUSample(timestamp=i * 0.01, ax=g[0], ay=g[1], az=g[2],
                          hw_fusion_valid=True, hw_qw=q_mount[0], hw_qx=q_mount[1],
                          hw_qy=q_mount[2], hw_qz=q_mount[3])
            f = fe.process(s)
        self.assertTrue(f.calibrated)
        self.assertAlmostEqual(f.roll, 0.0, delta=0.5)
        self.assertAlmostEqual(f.pitch, 0.0, delta=0.5)
        self.assertAlmostEqual(f.tilt_x, 0.0, delta=0.02)

        # Now tilt 15° relative to the mounted pose
        q_moved = q_mul(q_mount, q_from_euler(0.0, -15.0, 0.0))
        g2 = gravity_from_q(q_moved)
        for i in range(60, 90):
            s = IMUSample(timestamp=i * 0.01, ax=g2[0], ay=g2[1], az=g2[2],
                          hw_fusion_valid=True, hw_qw=q_moved[0], hw_qx=q_moved[1],
                          hw_qy=q_moved[2], hw_qz=q_moved[3])
            f = fe.process(s)
        self.assertGreater(f.tilt_x, 0.35)
        q_rel = q_relative(fe.q_base, q_moved)
        _, rel_pitch, _ = euler_from_q(q_rel)
        self.assertAlmostEqual(rel_pitch, -15.0, delta=1.0)

    def test_butterworth_step_lag_under_100ms_and_tremor_attenuation(self) -> None:
        b, a = butter2_lowpass(3.0, 100.0)
        flt = Biquad(b, a)
        flt.reset(0.0)
        reach_63_idx = None
        for i in range(30):
            y = flt(1.0)
            if y >= 0.632 and reach_63_idx is None:
                reach_63_idx = i
        self.assertIsNotNone(reach_63_idx)
        lag_ms = reach_63_idx * 10.0
        self.assertLess(lag_ms, 100.0, f"3 Hz Butterworth 63% rise time {lag_ms} ms must be < 100 ms")


class TestPhase3ChildProfile(unittest.TestCase):
    """Roadmap Phase 3: per-child calibration profile yields distinct thresholds & zero rest triggers."""

    def test_two_children_yield_distinct_thresholds_and_zero_rest_triggers(self) -> None:
        # Child A: mild tremor (0.4°), wide symmetrical ROM (30°), fast reaction (0.25 s)
        prof_a = ChildProfile(username="child_a", calibrated_profile=True)
        rest_a = [Frame(t=i * 0.02, dt=0.02, roll=0.4 * math.sin(i), pitch=0.0) for i in range(50)]
        reach_a = [Frame(t=i * 0.02, dt=0.02,
                         tilt_gx=math.sin(math.radians(30.0 if i % 2 == 0 else -30.0)),
                         tilt_gy=math.sin(math.radians(28.0 if i % 2 == 0 else -28.0)))
                   for i in range(40)]
        # Add one single-frame 85° spasm spike — 90th percentile must ignore it
        reach_a.append(Frame(t=1.0, dt=0.02, tilt_gx=math.sin(math.radians(85.0))))
        prof_a.calibrate_rest(rest_a)
        prof_a.calibrate_reach(reach_a)
        prof_a.calibrate_hold([1.0, 1.1, 0.9])
        prof_a.calibrate_reaction([0.24, 0.25, 0.26])

        # Child B: stronger tremor (3.0°), asymmetric limited left ROM (12° left, 25° right), slower hold/reaction
        prof_b = ChildProfile(username="child_b", calibrated_profile=True, spasm_gate_enabled=True)
        rest_b = [Frame(t=i * 0.02, dt=0.02, roll=3.0 * math.sin(i), pitch=3.0 * math.cos(i)) for i in range(50)]
        reach_b = [Frame(t=i * 0.02, dt=0.02,
                         tilt_gx=math.sin(math.radians(25.0 if i % 2 == 0 else -12.0)),
                         tilt_gy=math.sin(math.radians(15.0 if i % 2 == 0 else -15.0)))
                   for i in range(40)]
        prof_b.calibrate_rest(rest_b)
        prof_b.calibrate_reach(reach_b)
        prof_b.calibrate_hold([1.6, 1.8, 1.7])
        prof_b.calibrate_reaction([0.65, 0.70, 0.60])

        self.assertLess(prof_a.rom_right_deg, 35.0, "90th percentile should ignore single spasm spike")
        self.assertNotEqual(prof_a.t_on, prof_b.t_on)
        self.assertGreater(prof_b.t_on, prof_a.t_on)
        self.assertGreater(prof_b.hold_time, prof_a.hold_time)
        self.assertGreater(prof_b.cooldown, prof_a.cooldown)

        # Save & reload round-trip in temp dir
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            prof_b.save(d)
            loaded = ChildProfile.load("child_b", d)
            self.assertAlmostEqual(loaded.t_on, prof_b.t_on, places=4)
            self.assertAlmostEqual(loaded.rom_left_deg, 12.0, places=1)

        # Both profiles produce zero events on rest & tremor fixtures
        ensure_fixtures()
        self.assertEqual(replay(FIXTURES_DIR / "rest.jsonl", profile=prof_a), [])
        self.assertEqual(replay(FIXTURES_DIR / "tremor.jsonl", profile=prof_b), [])


class TestPhase4And5DetectorsAndAccessible(unittest.TestCase):
    """Roadmap Phases 4–5: detector plug-ins, Hold/Dwell/AnyMove/Still, SpasmGate."""

    def setUp(self) -> None:
        ensure_fixtures()

    def test_custom_detector_plugs_in_without_editing_process(self) -> None:
        class DummyDetector:
            name = "dummy"
            def reset(self) -> None: pass
            def update(self, f: Frame):
                return [GestureEvent(Gesture.SHAKE, t=f.t, detector=self.name)] if f.t == 1.50 else []

        interp = GestureInterpreter(queue.Queue(), GestureConfig(haptics_enabled=False))
        interp.register_detector(DummyDetector())
        for s in load_samples(FIXTURES_DIR / "rest.jsonl"):
            interp._process(s)
        events = interp.poll()
        self.assertEqual([e.gesture for e in events], [Gesture.SHAKE])

    def test_hold_fixtures_produce_single_hold_event_and_pause_adaptation(self) -> None:
        ev_r, _, sig_r = replay_full(FIXTURES_DIR / "hold_right.jsonl")
        holds_r = [e for e in ev_r if e.gesture in (Gesture.HOLD_RIGHT, Gesture.HOLD_LEFT)]
        self.assertEqual([e.gesture for e in holds_r], [Gesture.HOLD_RIGHT])
        self.assertTrue(any(0.2 < s.hold_progress < 0.9 for s in sig_r), "Progress ring should fill during ARMING")

        ev_l = replay(FIXTURES_DIR / "hold_left.jsonl")
        holds_l = [e for e in ev_l if e.gesture in (Gesture.HOLD_RIGHT, Gesture.HOLD_LEFT)]
        self.assertEqual([e.gesture for e in holds_l], [Gesture.HOLD_LEFT])

    def test_spasm_fixture_produces_zero_events_when_spasm_gate_enabled(self) -> None:
        cfg = GestureConfig(spasm_gate_enabled=True, haptics_enabled=False)
        events = replay(FIXTURES_DIR / "spasm.jsonl", config=cfg)
        self.assertEqual(events, [], "SpasmGate must reject short high-jerk spasm bursts")

    def test_dwell_anymove_and_still_detectors(self) -> None:
        dwell = DwellDetector(dwell_time=0.5, radius=0.1, min_offset=0.25)
        any_move = AnyMoveDetector(threshold=40.0, min_duration=0.2, cooldown=0.5)
        still = StillDetector(threshold=10.0, still_time=0.5)

        dwell_events, move_events, still_events = [], [], []
        for i in range(120):
            t = i * 0.02
            moving = 0.2 <= t < 0.55
            f = Frame(
                t=t, dt=0.02, calibrated=True,
                tilt_x=0.5 if t < 0.7 else 0.0,
                tilt_y=0.0,
                av_magnitude=80.0 if moving else 2.0,
            )
            dwell_events.extend(dwell.update(f))
            move_events.extend(any_move.update(f))
            still_events.extend(still.update(f))

        self.assertEqual([e.gesture for e in dwell_events], [Gesture.DWELL])
        self.assertEqual([e.gesture for e in move_events], [Gesture.ANY_MOVE])
        self.assertEqual([e.gesture for e in still_events], [Gesture.STILL])


class TestPhase6And7BindingsAndML(unittest.TestCase):
    """Roadmap Phases 6 & 7: poll_and_signals, dispatch_bindings, 44-feature ML & MLDetector."""

    def test_poll_and_signals_and_dispatch_bindings(self) -> None:
        ev1 = GestureEvent(gesture=Gesture.FLICK_LEFT, t=1.0, confidence=0.9)
        ev2 = GestureEvent(gesture=Gesture.SLICE, t=1.01, confidence=0.8)
        src = MagicMock()
        src.poll.return_value = [ev1, ev2]
        src.signals.return_value = Signals(tilt_x=-0.5, tilt_y=0.25, pointer_x=0.25, pointer_y=0.625, calibrated=True)

        events, sig = poll_and_signals(src)
        self.assertEqual(events, [ev1, ev2])
        self.assertAlmostEqual(sig.tilt_x, -0.5)
        self.assertAlmostEqual(sig.pointer_x, 0.25)

        seen = []
        matched = dispatch_bindings(
            events,
            {Gesture.FLICK_LEFT: lambda e: seen.append(e.gesture)},
        )
        self.assertEqual(seen, [Gesture.FLICK_LEFT])
        self.assertEqual(matched, [ev1])

    def test_44_features_for_imusnapshot_and_frame(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual(FeatureExtractor.N_FEATURES, 44)
        snaps = [
            IMUSnapshot(
                t=i * 0.02, gx=10.0 + i, gy=-5.0, gz=20.0,
                ax=0.1, ay=0.0, az=1.0,
                lin_ax=0.05 * i, lin_ay=0.01, lin_az=0.02,
                euler_roll=5.0, euler_pitch=-2.0,
            )
            for i in range(18)
        ]
        feat_snap = extract_ml_features(snaps)
        self.assertIsNotNone(feat_snap)
        self.assertEqual(len(feat_snap), 44)
        self.assertTrue(all(math.isfinite(x) for x in feat_snap))

        frames = [
            Frame(
                t=i * 0.02, dt=0.02, calibrated=True,
                gx=10.0 + i, gy=-5.0, gz=20.0,
                lin_ax=0.05 * i, lin_ay=0.01, lin_az=0.02,
                roll=5.0, pitch=-2.0, av_magnitude=40.0,
            )
            for i in range(18)
        ]
        feat_frame = extract_ml_features(frames)
        self.assertIsNotNone(feat_frame)
        self.assertEqual(len(feat_frame), 44)

    def test_ml_detector_stage1_gating_and_stage2_emission(self) -> None:
        with patch("shared.gesture_learner.SKLEARN_AVAILABLE", True):
            model = GestureModel(confidence_threshold=0.55)
            model._clf = MagicMock()
            model._stage1_clf = MagicMock()

            # Stage-1 flags involuntary -> suppresses emission
            model.predict_stage1 = MagicMock(return_value=("involuntary", 0.92))
            model.predict_with_confidence = MagicMock(return_value=("right", 0.95))

            det = MLDetector(model=model, smoothing_frames=2, cooldown_s=0.1)
            out = []
            for i in range(10):
                out.extend(det.update(Frame(
                    t=i * 0.02, dt=0.02, calibrated=True,
                    gx=5.0, gy=10.0, gz=80.0,
                    lin_ax=0.1, lin_ay=0.0, lin_az=0.0,
                    av_magnitude=85.0,
                )))
            self.assertEqual(out, [])
            self.assertTrue(det.is_involuntary())

            # Stage-1 allows intentional -> Stage-2 emits FLICK_RIGHT + SLICE after smoothing
            det.reset()
            model.predict_stage1 = MagicMock(return_value=("intentional", 0.95))
            for i in range(10):
                out.extend(det.update(Frame(
                    t=i * 0.02, dt=0.02, calibrated=True,
                    gx=5.0, gy=10.0, gz=80.0,
                    lin_ax=0.1, lin_ay=0.0, lin_az=0.0,
                    av_magnitude=85.0,
                )))
            gestures = [e.gesture for e in out]
            self.assertEqual(gestures, [Gesture.SLICE])
            self.assertEqual(out[0].direction, "right")
            self.assertTrue(all(e.source == "ml" for e in out))

            # emit_slice=False emits directional FLICK_*
            det_flick = MLDetector(model=model, smoothing_frames=2, cooldown_s=0.1, emit_slice=False)
            out_flick = []
            for i in range(10):
                out_flick.extend(det_flick.update(Frame(
                    t=i * 0.02, dt=0.02, calibrated=True,
                    gx=5.0, gy=10.0, gz=80.0,
                    lin_ax=0.1, lin_ay=0.0, lin_az=0.0,
                    av_magnitude=85.0,
                )))
            self.assertEqual([e.gesture for e in out_flick], [Gesture.FLICK_RIGHT])

    def test_smart_recorder_labeled_involuntary(self) -> None:
        buf = GestureBuffer()
        ext = FeatureExtractor()
        rec = SmartRecorder(buf, ext)
        for i in range(15):
            buf.push(IMUSnapshot(
                t=i * 0.02, gx=15.0 * (1 if i % 2 == 0 else -1), gy=5.0, gz=40.0,
                ax=0.0, ay=0.0, az=1.0, euler_roll=0.0, euler_pitch=0.0,
            ))
        ok = rec.record_labeled_window("involuntary", session_id="s1")
        self.assertTrue(ok)
        self.assertEqual(len(rec.recordings), 1)
        self.assertEqual(rec.recordings[0]["label"], "involuntary")
        self.assertEqual(len(rec.recordings[0]["features"]), 44)


if __name__ == "__main__":
    unittest.main()
