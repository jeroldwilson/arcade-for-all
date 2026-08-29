import math
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.dtw_learner import OrientationIndependentExtractor, DTWEngine, TemplateRefiner, IMUSnapshot

def test_dtw():
    print("Testing DTW Extractor...")
    extractor = OrientationIndependentExtractor()
    window = [
        IMUSnapshot(t=0, gx=10, gy=0, gz=0, ax=0, ay=0, az=1),
        IMUSnapshot(t=1, gx=10, gy=0, gz=0, ax=0, ay=0, az=1),
        IMUSnapshot(t=2, gx=10, gy=0, gz=0, ax=0, ay=0, az=1),
    ]
    curve = extractor.extract(window)
    print(f"Curve: {curve}")
    
    print("Testing DTW Engine...")
    template = [None, curve[1], curve[2]] # With star-padding
    dist = DTWEngine.distance(curve, template)
    print(f"Distance: {dist}")
    
    min_dist, start_idx, end_idx = DTWEngine.auto_segment(curve, template)
    print(f"Auto-segment: {min_dist}, {start_idx}, {end_idx}")
    
    print("Testing Template Refiner...")
    instances = [
        [1.0, 2.0, 3.0],
        [1.0, 2.1, 8.0],
        [1.0, 1.9, 9.0],
    ]
    refined = TemplateRefiner.refine(instances)
    print(f"Refined: {refined}")
    
    print("Success!")

if __name__ == "__main__":
    test_dtw()
