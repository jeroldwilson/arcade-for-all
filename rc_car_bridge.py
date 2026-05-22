"""
rc_car_bridge.py — Phase 5: Real World Application Bridge

This standalone script takes the AI model trained while playing Fruit Ninja
and uses it to output robotic driving commands.
"""

import time
from shared.sensor import MetaMotionSensor
from shared.gesture import GestureInterpreter
from shared.gesture_learner import GestureLearningSystem, PROFILE_ACCESSIBLE

def main():
    print("Starting MetaMotion BLE thread...")
    sensor = MetaMotionSensor()
    sensor.start_background()
    
    print("Initializing Interpreter...")
    interpreter = GestureInterpreter(sensor.data_queue, sensor=sensor)
    interpreter.start()
    
    print("Loading AI Model...")
    # Load the profile customized for the child
    learner = GestureLearningSystem(username="my_kid", profile=PROFILE_ACCESSIBLE)
    
    if not learner.model_ready:
        print("No trained model found! Please play Fruit Ninja in Learn Mode first to train the AI.")
        interpreter.stop()
        sensor.stop_background()
        return
        
    print("=== Bridge Active ===")
    print("Make a gesture. Outputting commands...")
    
    try:
        while True:
            time.sleep(0.01)
            gs = interpreter.get_state()
            learner.update(gs)
            
            # Let the AI model predict the intended direction based on raw gyro
            dx, dy = learner.get_cursor_delta(gs, scale_x=1.0, scale_y=1.0, dt=0.01)
            
            if dy > 0.2:
                print("SEND TO CAR: DRIVE_FORWARD")
            elif dy < -0.2:
                print("SEND TO CAR: DRIVE_BACKWARD")
            elif dx > 0.2:
                print("SEND TO CAR: STEER_RIGHT")
            elif dx < -0.2:
                print("SEND TO CAR: STEER_LEFT")
                
    except KeyboardInterrupt:
        print("\nShutting down bridge...")
    finally:
        interpreter.stop()
        sensor.stop_background()

if __name__ == "__main__":
    main()