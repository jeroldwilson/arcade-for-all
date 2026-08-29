# Audio Integration Plan

The goal is to replace the procedural numpy audio system with MP3 playback for background music (BGM), and add profile-specific MP3 events for encouragement (inaccessible/Astra mode) and success.

## Open Questions
- The `assets/audio/profiles/{username}/` folder might not exist for a newly created profile. Should the game silently fall back to no voice-overs if the folders don't exist, or is there a default profile audio folder? (I will implement a silent fallback).
- Should the procedural "collect" chime remain intact, or should we replace it? (I will leave the procedural collect chime as-is unless you specify otherwise, since it's snappy and doesn't interrupt MP3s).

## Proposed Changes

### `shared/audio.py`
Summary: Update `AudioEngine` to support MP3 playback using Pygame Mixer's music stream.
- **[MODIFY]** `shared/audio.py`
  - Remove or bypass the procedural `_generate_bgm()` logic.
  - Implement `start_background()` to `pygame.mixer.music.load()` the MP3 file at `assets/audio/shared/bgm/Building_Blocks_And_Bells.mp3` and play it on a loop.
  - Add `play_encourage(username)`: Pauses the BGM, randomly selects an MP3 from `assets/audio/profiles/{username}/Encourage/`, plays it, and sets an end event or check to resume BGM.
  - Add `play_success(username)`: Stops BGM, plays a random MP3 from `assets/audio/profiles/{username}/Success/`.
  - Add `update()` method to `AudioEngine` to check if an encourage MP3 has finished playing (using `pygame.mixer.music.get_busy()`) so it can resume the original BGM.

### `shared/game_experience.py`
Summary: Update `InactivityMonitor` to trigger the encouragement audio.
- **[MODIFY]** `shared/game_experience.py`
  - Pass the `AudioEngine` instance to `InactivityMonitor` so it can trigger audio.
  - In `update()`, when the inactivity threshold is reached and a "wake up" message is triggered, check if 50 seconds have passed since the last encourage voice-over. If so, call `audio.play_encourage(username)`.

### `games/fruit_ninja/game.py` (and others if necessary)
Summary: Pass the audio engine to `InactivityMonitor` and call `audio.play_success(username)` when the game is won.
- **[MODIFY]** `games/fruit_ninja/game.py`
  - Pass `self._audio` to `InactivityMonitor` during instantiation.
  - In the update loop, call `self._audio.update()` to manage the encourage-to-BGM transitions.
  - Call `self._audio.play_success(self._username)` when `self._goal.check_met()` returns True.

## Verification Plan
### Manual Verification
- Start the game and verify the MP3 BGM is playing instead of the procedural synth.
- Enter Accessible (Astra) mode, remain inactive to trigger the InactivityMonitor, and verify the encourage MP3 plays, BGM pauses, and BGM resumes after.
- Verify the 50-second cooldown on encourage audio.
- Hit the target score (e.g. 10k) and verify the success MP3 plays.
