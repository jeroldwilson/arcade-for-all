# Gameplay Experience Improvements 🚀

I've implemented the **Inactivity Feedback**, **Game Goals**, and **Visual Effects** for **Fruit Ninja**, which is the game you noted the kid liked most! We can test these out and then apply them to the other games if they work well.

## What's New

### 1. 📳 The "Wake Up" Sequence
If the player stops moving for **5 seconds**, the game will now trigger a "Wake Up" sequence:
- **Haptic Vibration**: The sensor will gently vibrate every 2 seconds.
- **Flashing LEDs**: The MetaMotion LED will blink in random colors.
- **On-Screen Encouragement**: Random flashing messages like *"Come on {username}, you can do it!"* or *"Make a move!"* will appear in the center of the screen to draw attention.

### 2. ⏸️ Auto-Pause and Resume
If the player continues to rest and inactivity reaches **15 seconds**:
- The game automatically goes into **PAUSED** mode.
- The sensor LED turns solid **Red**.
- **Resume by moving**: The instant the player moves their wrist, the game will automatically unpause, clear the messages, and the LED will turn back to solid **Green**.

### 3. 🎯 Game Goals
Before starting a game, you'll now be presented with a menu to set a goal:
- **Score Targets** (e.g. 20 points, 50 points)
- **Time Limits** (e.g. 2 minutes, 5 minutes)
- **Endless Play**

### 4. 🎆 Visual Effects & Celebration
- **Slice Particles**: When a fruit is sliced, a burst of colorful particles appears for extra visual reward.
- **Game Over Celebration**: When a Game Goal is reached, a **fireworks effect** (60 particles) will trigger on-screen, synchronized with a sensor vibration and a flashing LED burst!

### 5. 🧲 Reduced Auto-Aim Magnetism
As planned, I reduced the `AUTO_AIM_PULL` from `580` to `250` in Accessible mode. 
I also added an **Intent Check**: the auto-aim will now only pull the cursor toward the fruit if the player is swinging in the general direction of the fruit (within a ~70-degree cone), preventing the cursor from fighting against intentional swings.

## How to Test
1. Run **Fruit Ninja** in **Accessible (Astra)** mode.
2. At the start, pick a goal (e.g., Score Target: 20).
3. Try resting your wrist for 5 seconds to see the haptics, LEDs, and encouraging messages.
4. Keep resting for another 10 seconds to watch it Auto-Pause.
5. Move your wrist to automatically resume!
6. Reach the score target to see the fireworks celebration.

Let me know how this feels during playtesting! If it's a hit, I'll quickly roll these identical features out to **Bricks** and **Snake**.
