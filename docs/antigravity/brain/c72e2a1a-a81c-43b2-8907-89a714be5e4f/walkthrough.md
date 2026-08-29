# Audio MP3 Integration

I've completely overhauled the audio system to use your custom MP3 files instead of the procedural synthesizers! 

## Background Music (BGM)
The game now uses Pygame's `mixer.music` to stream `Building_Blocks_And_Bells.mp3` as the background music across all games.

## Profile Voiceovers & Encouragement
When playing in **Accessible Mode** (Astra mode), if a player stops moving and triggers the "Wake Up" inactivity monitor:
- The game now dynamically checks the `assets/audio/profiles/[USERNAME]/Encourage/` folder.
- If it finds MP3s, it automatically **pauses the BGM** and plays a random encouraging voiceover on a dedicated audio channel.
- Once the voiceover finishes playing, the game seamlessly **resumes the BGM**.
- To prevent spamming, I added a **50-second cooldown** between voiceovers so the player isn't overwhelmed.

## Success Fanfare
When the player reaches the target goal (e.g., hitting a 200 Score Target):
- The background music is fully stopped.
- The game plays a random success MP3 from `assets/audio/profiles/[USERNAME]/Success/`.

## Testing It Out
You can test these features right away by starting the game with `python main.py`, selecting the `Srihari` profile, jumping into Fruit Ninja on Accessible mode, and letting the game idle for a few seconds to hear the new audio engine in action!
