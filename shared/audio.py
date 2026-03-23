"""
audio.py — Procedural audio for MetaMotion Arcade

All sounds are generated from numpy arrays at runtime (no external files).

Background music: upbeat kids-friendly adventure theme, 120 BPM, C major.
  • Four 4-bar phrases that loop seamlessly (~16 s loop).
  • Melody uses a bright square-wave timbre (odd harmonics) — classic game sound.
  • Bass line uses a warm triangle-wave timbre.
  • Tracks are mixed at safe levels to avoid clipping.

Collect sound: bright rising chime played when a fruit / brick is collected.
"""

import numpy as np
import pygame

_PI2 = 2.0 * np.pi

# ── Note table (Hz) ───────────────────────────────────────────────────────────

NOTES = {
    # Bass register
    'C3':  130.81, 'E3':  164.81, 'F3':  174.61,
    'G3':  196.00, 'A3':  220.00, 'B3':  246.94,
    # Mid register
    'C4':  261.63, 'D4':  293.66, 'E4':  329.63,
    'F4':  349.23, 'G4':  392.00, 'A4':  440.00, 'B4':  493.88,
    # High register
    'C5':  523.25, 'D5':  587.33, 'E5':  659.25,
    'F5':  698.46, 'G5':  783.99, 'A5':  880.00, 'B5':  987.77,
    'C6': 1046.50,
    # Rest
    'R':     0.0,
}

# ── 120 BPM note-length constants (seconds) ───────────────────────────────────
_Q  = 0.500   # quarter note
_E  = 0.250   # eighth note
_H  = 1.000   # half note
_DE = 0.375   # dotted eighth


# ── Upbeat kids-friendly melody (4 phrases × 4 bars) ─────────────────────────
#
# Each phrase is exactly 4.0 s at 120 BPM (8 quarter-note beats).
#
# Phrase A  — bright opening hook
# Phrase B  — playful bouncing response
# Phrase C  — energy build-up to the high register
# Phrase D  — triumphant resolution back to root
#
_MELODY = [
    # ── Phrase A: catchy opening hook ─────────────────────────────────────────
    ('E5', _E), ('G5', _E), ('A5', _E), ('G5', _E),
    ('E5', _Q), ('C5', _Q),
    ('D5', _E), ('E5', _E), ('D5', _E), ('C5', _E),
    ('C5', _H),

    # ── Phrase B: playful bounce ───────────────────────────────────────────────
    ('G4', _E), ('A4', _E), ('C5', _E), ('E5', _E),
    ('D5', _E), ('C5', _E), ('D5', _Q),
    ('E5', _E), ('D5', _E), ('C5', _E), ('A4', _E),
    ('C5', _H),

    # ── Phrase C: energy climb ─────────────────────────────────────────────────
    ('C5', _E), ('E5', _E), ('G5', _E), ('A5', _E),
    ('G5', _Q), ('E5', _Q),
    ('A5', _E), ('G5', _E), ('E5', _E), ('D5', _E),
    ('E5', _H),

    # ── Phrase D: triumphant resolution ───────────────────────────────────────
    ('G5', _E), ('E5', _E), ('G5', _E), ('A5', _E),
    ('G5', _Q), ('E5', _Q),
    ('D5', _E), ('E5', _E), ('D5', _E), ('C5', _E),
    ('C5', _H),
]

# ── Bass line — one note per quarter beat, same total duration as melody ───────
_BASS = [
    # Phrase A (8 quarter beats = 4.0 s)
    ('C3', _Q), ('C3', _Q), ('G3', _Q), ('G3', _Q),
    ('F3', _Q), ('F3', _Q), ('G3', _Q), ('G3', _Q),

    # Phrase B
    ('C3', _Q), ('C3', _Q), ('F3', _Q), ('G3', _Q),
    ('C3', _Q), ('G3', _Q), ('C3', _H),

    # Phrase C
    ('C3', _Q), ('E3', _Q), ('G3', _Q), ('A3', _Q),
    ('F3', _Q), ('F3', _Q), ('G3', _Q), ('G3', _Q),

    # Phrase D
    ('C3', _Q), ('G3', _Q), ('C3', _Q), ('G3', _Q),
    ('F3', _Q), ('G3', _Q), ('C3', _H),
]


# ── Core audio manager ─────────────────────────────────────────────────────────

class AudioManager:
    """
    Procedural music and sound effects for MetaMotion Arcade.

    Public API
    ──────────
      start_background()   — loop the gameplay music
      stop_background()    — stop music (e.g. on home screen)
      play_collect()       — play fruit/brick-collect chime
    """

    def __init__(self) -> None:
        info = pygame.mixer.get_init()
        if not info:
            pygame.mixer.init(44100, -16, 2, 512)
            info = pygame.mixer.get_init()
        self._rate  = info[0]
        self._chans = info[2]

        self._bg_sound      = self._to_sound(self._build_bg_loop())
        self._collect_sound = self._to_sound(self._build_collect())

        self._bg_sound.set_volume(0.30)
        self._collect_sound.set_volume(0.70)

    # ── Wave generators ───────────────────────────────────────────────────────

    def _square_tone(self, freq: float, dur: float, amp: float = 0.14) -> np.ndarray:
        """
        Bright square-wave-ish tone built from odd harmonics.
        Great for melodic leads — sounds like classic 8-bit game music.
        """
        if freq <= 0 or dur <= 0:
            return np.zeros(max(1, int(self._rate * dur)), dtype=np.int16)
        n = int(self._rate * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        # Odd harmonic series approximates a square wave
        wave = (
            np.sin(_PI2 * freq       * t)
          + 0.333 * np.sin(_PI2 * freq * 3 * t)   # 3rd harmonic
          + 0.200 * np.sin(_PI2 * freq * 5 * t)   # 5th harmonic
          + 0.143 * np.sin(_PI2 * freq * 7 * t)   # 7th harmonic
        )
        wave *= amp / 1.676   # normalise sum of amplitudes
        # Snappy ADSR: very fast attack, gentle release (preserves rhythm)
        env  = np.ones(n, dtype=np.float32)
        att  = max(1, int(n * 0.03))
        rel  = max(1, int(n * 0.28))
        env[:att]  = np.linspace(0.0, 1.0, att)
        env[-rel:] = np.linspace(1.0, 0.0, rel)
        return (wave * env * 32767).clip(-32767, 32767).astype(np.int16)

    def _triangle_tone(self, freq: float, dur: float, amp: float = 0.16) -> np.ndarray:
        """
        Warm triangle-wave tone (mellow, great for bass).
        Triangle wave = odd harmonics with amplitude ∝ 1/n².
        """
        if freq <= 0 or dur <= 0:
            return np.zeros(max(1, int(self._rate * dur)), dtype=np.int16)
        n = int(self._rate * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        wave = (
            np.sin(_PI2 * freq       * t)
          - 0.111 * np.sin(_PI2 * freq * 3 * t)   # 3rd (negative for triangle shape)
          + 0.040 * np.sin(_PI2 * freq * 5 * t)
          - 0.020 * np.sin(_PI2 * freq * 7 * t)
        )
        wave *= amp / 1.171
        env  = np.ones(n, dtype=np.float32)
        att  = max(1, int(n * 0.02))
        rel  = max(1, int(n * 0.40))   # longer release for warmth
        env[:att]  = np.linspace(0.0, 1.0, att)
        env[-rel:] = np.linspace(1.0, 0.0, rel)
        return (wave * env * 32767).clip(-32767, 32767).astype(np.int16)

    # ── Track builders ────────────────────────────────────────────────────────

    def _build_melody_track(self) -> np.ndarray:
        parts = [self._square_tone(NOTES[n], d, amp=0.13) for n, d in _MELODY]
        return np.concatenate(parts).astype(np.float32)

    def _build_bass_track(self) -> np.ndarray:
        parts = [self._triangle_tone(NOTES[n], d, amp=0.14) for n, d in _BASS]
        arr   = np.concatenate(parts).astype(np.float32)
        # Pad or trim so bass matches melody length exactly
        mel_len = sum(int(self._rate * d) for _, d in _MELODY)
        if len(arr) < mel_len:
            arr = np.concatenate([arr, np.zeros(mel_len - len(arr), dtype=np.float32)])
        else:
            arr = arr[:mel_len]
        return arr

    def _build_bg_loop(self) -> np.ndarray:
        """Mix melody + bass into a single loopable int16 buffer."""
        mel  = self._build_melody_track()
        bass = self._build_bass_track()
        # Mix at balanced levels — melody slightly louder
        mixed = mel * 0.58 + bass * 0.42
        # Soft-clip to prevent inter-channel distortion on mix
        mixed = np.tanh(mixed / 32767) * 32767
        return mixed.clip(-32767, 32767).astype(np.int16)

    def _build_collect(self) -> np.ndarray:
        """Rising 3-note chime — bright and rewarding."""
        return np.concatenate([
            self._square_tone(NOTES['E5'], 0.07, amp=0.30),
            self._square_tone(NOTES['G5'], 0.07, amp=0.30),
            self._square_tone(NOTES['C6'], 0.20, amp=0.28),
        ])

    # ── pygame.Sound wrapper ──────────────────────────────────────────────────

    def _to_sound(self, mono: np.ndarray) -> "pygame.mixer.Sound":
        data = np.column_stack([mono, mono]) if self._chans == 2 else mono
        return pygame.sndarray.make_sound(np.ascontiguousarray(data))

    # ── Public API ────────────────────────────────────────────────────────────

    def start_background(self) -> None:
        self._bg_sound.play(loops=-1)

    def stop_background(self) -> None:
        self._bg_sound.stop()

    def play_collect(self) -> None:
        self._collect_sound.play()


# ── Silent fallback ───────────────────────────────────────────────────────────

class _NullAudio:
    """No-op audio used when mixer is unavailable."""
    def start_background(self) -> None: pass
    def stop_background(self)  -> None: pass
    def play_collect(self)     -> None: pass


def make_audio_manager():
    """Return an AudioManager, or a silent fallback if audio init fails."""
    try:
        return AudioManager()
    except Exception as exc:
        print(f"[audio] Audio unavailable ({exc}). Running silent.")
        return _NullAudio()
