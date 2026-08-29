"""
shared/assets.py — Centralized image asset loader with caching.

All game art (fruits, blade, bomb) lives in assets/ at the project root.
Assets are JPG (black background) so we use colorkey=(0,0,0) for transparency.
"""

import pathlib
import functools
import pygame

ASSET_DIR = pathlib.Path(__file__).parent.parent / "assets" / "images"


@functools.lru_cache(maxsize=256)
def load_sprite(name: str, size: int) -> pygame.Surface:
    """Load a game asset by filename, scale to size x size px.

    Uses black as a colorkey for transparency (assets have pure black bg).
    Returns a colored placeholder circle if the file is not found.
    """
    path = ASSET_DIR / name
    if path.exists():
        img = pygame.image.load(str(path)).convert_alpha()
        
        # Lock pixels to modify the background (remove near-black pixels)
        px = pygame.PixelArray(img)
        for x in range(img.get_width()):
            for y in range(img.get_height()):
                c = img.unmap_rgb(px[x, y])
                if c.r < 35 and c.g < 35 and c.b < 35:
                    px[x, y] = (0, 0, 0, 0)
        px.close()
        
        return pygame.transform.smoothscale(img, (size, size))

    # Graceful fallback
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    _FALLBACK_COLORS = {
        "watermelon": (220, 50, 50),
        "strawberry": (220, 60, 80),
        "orange":     (245, 145, 30),
        "pineapple":  (240, 210, 40),
        "mango":      (255, 170, 30),
        "kiwi":       (80, 200, 60),
        "cherry":     (180, 20, 40),
        "peach":      (255, 160, 120),
        "bomb":       (40,  40,  40),
        "katana":     (180, 200, 255),
    }
    key = next((k for k in _FALLBACK_COLORS if k in name), None)
    color = _FALLBACK_COLORS.get(key, (160, 160, 160)) if key else (160, 160, 160)
    pygame.draw.circle(surf, (*color, 220), (size // 2, size // 2), size // 2 - 2)
    pygame.draw.circle(surf, (255, 255, 255, 80), (size // 3, size // 3), size // 6)
    return surf


# ── Fruit catalog ─────────────────────────────────────────────────────────────

FRUIT_CATALOG = [
    {"id": "watermelon", "asset": "fruit_watermelon.jpg", "slice_asset": "fruit_watermelon_slice.jpg", "juice_color": (220, 30,  50),  "points": 20, "radius_frac": 0.42, "size_multiplier": 2.0},
    {"id": "pineapple",  "asset": "fruit_pineapple.jpg",  "slice_asset": "fruit_pineapple_slice.jpg",  "juice_color": (240, 210, 40),  "points": 15, "radius_frac": 0.35, "size_multiplier": 1.5},
    {"id": "mango",      "asset": "fruit_mango.jpg",      "slice_asset": "fruit_mango_slice.jpg",      "juice_color": (255, 165, 30),  "points": 15, "radius_frac": 0.40, "size_multiplier": 1.25},
    {"id": "orange",     "asset": "fruit_orange.jpg",     "slice_asset": "fruit_orange_slice.jpg",     "juice_color": (245, 140, 30),  "points": 10, "radius_frac": 0.40, "size_multiplier": 1.0},
    {"id": "peach",      "asset": "fruit_peach.jpg",      "slice_asset": "fruit_peach_slice.jpg",      "juice_color": (255, 150, 100), "points": 10, "radius_frac": 0.40, "size_multiplier": 1.0},
    {"id": "kiwi",       "asset": "fruit_kiwi.jpg",       "slice_asset": "fruit_kiwi_slice.jpg",       "juice_color": (60,  200, 60),  "points": 10, "radius_frac": 0.40, "size_multiplier": 0.9},
    {"id": "strawberry", "asset": "fruit_strawberry.jpg", "slice_asset": "fruit_strawberry_slice.jpg", "juice_color": (230, 50,  80),  "points": 10, "radius_frac": 0.38, "size_multiplier": 0.75},
    {"id": "cherry",     "asset": "fruit_cherry.jpg",     "slice_asset": "fruit_cherry_slice.jpg",     "juice_color": (180, 10,  40),  "points": 25, "radius_frac": 0.30, "size_multiplier": 0.75},
]
