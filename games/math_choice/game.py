import pygame
import random
import sys
import time

from shared.gesture import CONFIG_ACCESSIBLE_FLICK_STEER
from shared.gesture_hud import GestureHUD

class MathChoiceGame:
    def __init__(self, screen, clock, debug, mode, audio, username):
        self.screen = screen
        self.clock = clock
        self.debug = debug
        self.mode = mode  # "astra" or "veera"
        self.audio = audio
        self.username = username
        self.W, self.H = screen.get_size()
        self.sc = min(self.W / 800, self.H / 600)
        
        # Load fonts
        if not pygame.font.get_init():
            pygame.font.init()
        self.font_title = pygame.font.SysFont("Arial", int(80 * self.sc), bold=True)
        self.font_problem = pygame.font.SysFont("Arial", int(120 * self.sc), bold=True)
        self.font_answer = pygame.font.SysFont("Arial", int(150 * self.sc), bold=True)
        self.font_feedback = pygame.font.SysFont("Arial", int(60 * self.sc), bold=True)

        self.hud = GestureHUD("/Users/jerold/.gemini/antigravity-ide/brain/3c53c120-8bf4-4a05-a904-340edfef9b68/metamotion_kid_hand_flat_1788027714986.jpg", scale=0.3)

        self.score = 0
        self.streak = 0
        self.generate_problem()
        
        self.selector_pos = self.W / 2
        self.dwell_timer = 0
        self.dwell_side = None
        self.dwell_required = 1.5  # seconds
        self.feedback_timer = 0
        self.feedback_text = ""
        self.feedback_color = (255, 255, 255)

    def generate_problem(self):
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        self.correct_answer = a * b
        wrong_offset = random.choice([-2, -1, 1, 2, 10, -10])
        wrong_answer = self.correct_answer + wrong_offset
        if wrong_answer <= 0: wrong_answer = 1
        
        self.problem_text = f"{a} x {b}"
        if random.random() > 0.5:
            self.left_ans = self.correct_answer
            self.right_ans = wrong_answer
        else:
            self.left_ans = wrong_answer
            self.right_ans = self.correct_answer

    def check_answer(self, side):
        if side == "left" and self.left_ans == self.correct_answer:
            self.handle_correct()
        elif side == "right" and self.right_ans == self.correct_answer:
            self.handle_correct()
        else:
            self.handle_wrong()

    def handle_correct(self):
        self.score += 1
        self.streak += 1
        self.audio.play("powerup")
        self.feedback_text = "CORRECT!"
        self.feedback_color = (100, 255, 100)
        self.feedback_timer = 1.5
        self.generate_problem()
        self.dwell_timer = 0

    def handle_wrong(self):
        self.streak = 0
        self.audio.play("brick_hit")
        self.feedback_text = "TRY AGAIN!"
        self.feedback_color = (255, 100, 100)
        self.feedback_timer = 1.5
        self.dwell_timer = 0

    def run(self, interpreter):
        if interpreter and getattr(interpreter, "config", None) is not None:
            interpreter.config = CONFIG_ACCESSIBLE_FLICK_STEER
        
        running = True
        dt = 0
        
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return "home"
                    elif event.key == pygame.K_d:
                        self.debug = not self.debug

            if interpreter:
                gs = interpreter.get_state()
            else:
                gs = None
            
            # --- UPDATE ---
            if self.feedback_timer > 0:
                self.feedback_timer -= dt
                # Reset selector while showing feedback
                self.selector_pos = self.W / 2
                self.dwell_timer = 0
            else:
                if gs:
                    # Continuous control
                    speed = 600 * self.sc * gs.paddle_velocity * dt
                    self.selector_pos += speed
                    self.selector_pos = max(0, min(self.W, self.selector_pos))
                    
                    current_side = None
                    if self.selector_pos < self.W * 0.35:
                        current_side = "left"
                    elif self.selector_pos > self.W * 0.65:
                        current_side = "right"
                    
                    if current_side:
                        if current_side == self.dwell_side:
                            self.dwell_timer += dt
                            if self.dwell_timer >= self.dwell_required:
                                self.check_answer(current_side)
                        else:
                            self.dwell_side = current_side
                            self.dwell_timer = dt
                    else:
                        self.dwell_side = None
                        self.dwell_timer = 0
                        
                    # Discrete control (flick steering)
                    if gs.steer_left:
                        self.check_answer("left")
                    elif gs.steer_right:
                        self.check_answer("right")

            # --- RENDER ---
            self.screen.fill((20, 20, 30))
            
            # Draw split screen divider
            pygame.draw.line(self.screen, (50, 50, 70), (self.W // 2, 0), (self.W // 2, self.H), 4)

            # Draw Answers
            l_surf = self.font_answer.render(str(self.left_ans), True, (255, 220, 100))
            r_surf = self.font_answer.render(str(self.right_ans), True, (255, 220, 100))
            self.screen.blit(l_surf, l_surf.get_rect(center=(self.W * 0.25, self.H * 0.6)))
            self.screen.blit(r_surf, r_surf.get_rect(center=(self.W * 0.75, self.H * 0.6)))

            # Draw Problem
            prob_surf = self.font_problem.render(self.problem_text, True, (255, 255, 255))
            # Draw shadow
            prob_shadow = self.font_problem.render(self.problem_text, True, (0, 0, 0))
            self.screen.blit(prob_shadow, prob_shadow.get_rect(center=(self.W // 2 + 4, self.H * 0.2 + 4)))
            self.screen.blit(prob_surf, prob_surf.get_rect(center=(self.W // 2, self.H * 0.2)))

            # Draw Feedback
            if self.feedback_timer > 0:
                fb_surf = self.font_feedback.render(self.feedback_text, True, self.feedback_color)
                self.screen.blit(fb_surf, fb_surf.get_rect(center=(self.W // 2, self.H * 0.4)))

            # Draw Dwell indicator and Selector
            if self.feedback_timer <= 0:
                # The selector is a circle that moves left/right
                sel_y = self.H * 0.8
                pygame.draw.circle(self.screen, (200, 200, 255), (int(self.selector_pos), int(sel_y)), int(20 * self.sc))
                
                # Draw dwell progress
                if self.dwell_side and self.dwell_timer > 0:
                    prog = min(1.0, self.dwell_timer / self.dwell_required)
                    target_x = self.W * 0.25 if self.dwell_side == "left" else self.W * 0.75
                    pygame.draw.rect(self.screen, (100, 255, 100), (target_x - 100, sel_y - 10, 200 * prog, 20))
                    pygame.draw.rect(self.screen, (255, 255, 255), (target_x - 100, sel_y - 10, 200, 20), 2)

            # Draw Score
            score_txt = self.font_feedback.render(f"Score: {self.score}", True, (150, 150, 150))
            self.screen.blit(score_txt, (20, 20))

            # Draw HUD
            if gs:
                self.hud.draw(self.screen, gs, self.W - 100, self.H - 100)

            pygame.display.flip()
            dt = self.clock.tick(60) / 1000.0

def run(screen, clock, debug, mode, audio, username, interpreter):
    game = MathChoiceGame(screen, clock, debug, mode, audio, username)
    return game.run(interpreter)
