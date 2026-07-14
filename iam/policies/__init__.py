"""业务资源的授权策略。"""

from .candidate_policy import CandidatePolicy
from .position_policy import PositionPolicy
from .resume_policy import ResumePolicy

__all__ = ["CandidatePolicy", "PositionPolicy", "ResumePolicy"]
