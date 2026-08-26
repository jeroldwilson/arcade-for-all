from typing import Optional, Tuple, List
from shared.gesture_learner import GestureLearningSystem, GestureProfile, PROFILE_STANDARD
from shared.dtw_learner import DTWLearningSystem

class GestureEngineManager:
    """
    Manages switching between the Random Forest (v1) and DTW (v2) learning engines.
    Exposes the same interface as GestureLearningSystem.
    """
    DEFAULT_ENGINE = "rf"

    def __init__(self, username: str = "", profile: Optional[GestureProfile] = None):
        self._username = username
        self._profile = profile or PROFILE_STANDARD
        
        self.rf_engine = GestureLearningSystem(username, self._profile)
        self.dtw_engine = DTWLearningSystem(username, self._profile)
        
        self.use_dtw = (self.DEFAULT_ENGINE == "dtw")
        
    @property
    def current_engine(self):
        return self.dtw_engine if self.use_dtw else self.rf_engine
        
    def toggle_engine(self) -> str:
        self.use_dtw = not self.use_dtw
        return "DTW (v2)" if self.use_dtw else "Random Forest (v1)"
        
    def set_profile(self, profile: GestureProfile) -> None:
        self._profile = profile
        self.rf_engine.set_profile(profile)
        self.dtw_engine.set_profile(profile)
        
    def update(self, gs) -> None:
        # Both buffers need to be updated simultaneously so they are 
        # ready if the user hot-swaps engines
        self.rf_engine.update(gs)
        self.dtw_engine.update(gs)
        
    def try_record(self, gs, blade_xy: Tuple[float, float], fruits_xy: List[Tuple[float, float]], mode: str = "standard") -> bool:
        return self.current_engine.try_record(gs, blade_xy, fruits_xy, mode)
        
    def predict(self, gs) -> Tuple[Optional[str], float]:
        return self.current_engine.predict(gs)
        
    def get_cursor_delta(self, gs, scale_x: float, scale_y: float, dt: float) -> Tuple[float, float]:
        return self.current_engine.get_cursor_delta(gs, scale_x, scale_y, dt)
        
    def save_and_train(self) -> bool:
        return self.current_engine.save_and_train()
        
    def start_validation(self) -> None:
        self.current_engine.start_validation()
        
    @property
    def validation_running(self) -> bool:
        return self.current_engine.validation_running
        
    @property
    def validation_result(self):
        return self.current_engine.validation_result
        
    @property
    def rec_flash_active(self) -> bool:
        return self.current_engine.rec_flash_active
        
    @property
    def total_recordings(self) -> int:
        return self.current_engine.total_recordings
        
    @property
    def model_ready(self) -> bool:
        return self.current_engine.model_ready
        
    @property
    def sklearn_available(self) -> bool:
        return self.current_engine.sklearn_available
        
    @property
    def class_balance_ok(self) -> bool:
        return self.current_engine.class_balance_ok
        
    @property
    def class_counts(self):
        return self.current_engine.class_counts
        
    @property
    def saved_sample_count(self) -> int:
        return self.current_engine.saved_sample_count
