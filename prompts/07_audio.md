# Prompt: Audio Manager (`shared/audio.py`)

## Task
Implement a thin audio abstraction that plays background music and sound effects for the arcade games. The manager must degrade gracefully if `pygame.mixer` fails (e.g., no audio device).

## Class interface
```python
def make_audio_manager() -> AudioManager:
    """Factory — returns a real AudioManager or a NullAudioManager on failure."""

class AudioManager:
    def start_background(self) -> None   # play looping background track
    def stop_background(self) -> None    # stop background track
    def play_sfx(self, name: str) -> None  # play a one-shot sound effect

class NullAudioManager:
    """No-op implementation — all methods are silent stubs."""
```

## Background music
- Loop a single ambient track (`.ogg` or `.wav`) while in a game
- Volume: ~0.4 (out of 1.0) to not overpower SFX
- Stop when returning to home screen; optionally play a quieter track on home screen

## Sound effects
| Name | When to play |
|------|-------------|
| `"bounce"` | Ball bounces off paddle or wall |
| `"brick"` | Ball destroys a brick |
| `"powerup"` | Player collects a power-up |
| `"launch"` | Ball is launched |
| `"lost_life"` | Ball falls below paddle (standard) |
| `"gameover"` | No lives remaining |
| `"level_up"` | All bricks cleared → next level |
| `"eat"` | Snake eats food |
| `"snake_die"` | Snake hits self |

## File layout
```
shared/
└── audio.py
assets/
└── sounds/
    ├── background.ogg
    ├── bounce.wav
    ├── brick.wav
    ├── powerup.wav
    ├── launch.wav
    ├── lost_life.wav
    ├── gameover.wav
    ├── level_up.wav
    ├── eat.wav
    └── snake_die.wav
```

## Implementation
```python
import pygame

class AudioManager:
    def __init__(self):
        self._sounds = {}
        self._bg_channel = None
        self._load_sounds()

    def _load_sounds(self):
        import os
        base = os.path.join(os.path.dirname(__file__), "..", "assets", "sounds")
        for name in [...]:
            path = os.path.join(base, f"{name}.wav")
            if os.path.exists(path):
                self._sounds[name] = pygame.mixer.Sound(path)

    def play_sfx(self, name: str) -> None:
        if name in self._sounds:
            self._sounds[name].play()

    def start_background(self) -> None:
        path = os.path.join(base, "background.ogg")
        if os.path.exists(path):
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.4)
            pygame.mixer.music.play(-1)   # loop

    def stop_background(self) -> None:
        pygame.mixer.music.stop()

def make_audio_manager() -> AudioManager:
    try:
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()
        return AudioManager()
    except Exception:
        return NullAudioManager()
```

## Notes
- `pygame.mixer.pre_init()` is called in `main.py` before `pygame.init()` — do not call it again inside the audio manager
- Games call `audio.play_sfx("bounce")` etc. — they do not import pygame.mixer directly
- If `audio` is `None` (passed from old call sites), all calls are no-ops
- NullAudioManager is also used in keyboard-only mode if audio init fails
