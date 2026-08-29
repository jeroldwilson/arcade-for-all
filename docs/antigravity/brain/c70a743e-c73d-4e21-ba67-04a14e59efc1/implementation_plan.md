# Animated Inactivity Character for Astra Mode

Currently, when the player stops moving, `InactivityMonitor` plays audio and displays a text message. We will enhance this by showing an animated mango character waving at the user, with the text message displayed below it.

## Question: GIF vs PNG?
**We should use PNGs.** Pygame does *not* natively support animated GIFs out-of-the-box. The standard and most performant way to animate in Pygame is to use either:
1. **A Spritesheet** (a single PNG containing all frames side-by-side)
2. **Procedural Animation** (a single static PNG that we rotate and scale using Pygame code to simulate "waving" or "breathing").

Since getting AI to generate a perfectly consistent frame-by-frame spritesheet can be difficult, **I recommend Procedural Animation**. We will generate a single high-quality PNG of a mango with hands and legs, and use Pygame to make it wave back and forth! If you prefer a traditional spritesheet, the code will also be designed to easily drop one in later.

## Proposed Changes

### 1. Asset Generation
- Generate a new image: a cute mango character with hands and legs on a transparent background.
- Save it to an `assets/` directory (e.g., `assets/wake_mango.png`).

### 2. `shared/game_experience.py` (`InactivityMonitor`)
- **Initialize Animation**: Load `assets/wake_mango.png` during `InactivityMonitor.__init__`. 
- **Animation State**: Add variables to track time (`self._anim_timer`) for smooth sinusoidal rotation.
- **Draw Logic**: 
  - Update `draw(self, screen)` to calculate a waving angle using `math.sin(time.time() * speed)`.
  - Rotate the mango image and blit it to the center of the screen.
  - Render the existing text message directly below the bounding box of the mango image.

## Open Questions
- Do you want me to generate the mango character image right now using my image generation tool, or do you already have an image you want to use?
- If I generate it, would you prefer a 2D cartoon style, or something more 3D/rendered?
