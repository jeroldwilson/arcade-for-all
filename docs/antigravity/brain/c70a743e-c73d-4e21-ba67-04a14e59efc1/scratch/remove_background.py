import sys
import os
import pygame

def remove_background(input_path, output_path):
    pygame.init()
    # Use headless mode for pygame since we are in terminal
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    
    img = pygame.image.load(input_path).convert_alpha()
    width, height = img.get_size()
    
    visited = set()
    to_visit = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    
    def is_background(r, g, b):
        sat = max(r, g, b) - min(r, g, b)
        val = (int(r) + int(g) + int(b)) / 3
        return sat < 30 and val > 120

    # Direct pixel manipulation using PixelArray
    pixel_array = pygame.PixelArray(img)
    
    while to_visit:
        x, y = to_visit.pop(0)
        if (x, y) in visited:
            continue
        visited.add((x, y))
        
        # In pygame, color is mapped to 32-bit int
        color = pixel_array[x, y]
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        
        if is_background(r, g, b):
            # Set alpha to 0 (make transparent)
            pixel_array[x, y] = pygame.Color(0, 0, 0, 0)
            
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                    to_visit.append((nx, ny))
                    
    del pixel_array # Free lock on surface
    
    # Save the processed image
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pygame.image.save(img, output_path)
    print(f"Saved transparent image to {output_path}")

if __name__ == "__main__":
    input_img = "/Users/jerold/.gemini/antigravity-ide/brain/c70a743e-c73d-4e21-ba67-04a14e59efc1/mango_character_1787542784829.jpg"
    output_img = "/Users/jerold/dev/Bricks/assets/images/mango_character.png"
    remove_background(input_img, output_img)
