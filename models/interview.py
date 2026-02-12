import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel
from .user import UserModel
from .candidate import CandidateModel


class InterviewResultEnum(str, enum.Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InterviewModel(BaseModel):
    __tablename__ = "interviews"

    scheduled_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    result: Mapped[Optional[InterviewResultEnum]] = mapped_column(Enum(InterviewResultEnum))

    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), unique=True)
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    candidate: Mapped["CandidateModel"] = relationship(back_populates="interviews")
    interviewer: Mapped["UserModel"] = relationship()


CandidateModel.interviews = relationship("InterviewModel", back_populates="candidate")


# 工作区 ->(git add .) -> 暂存区 ->(git commit) -> 仓库