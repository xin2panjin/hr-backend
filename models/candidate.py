import enum
from typing import Optional

from sqlalchemy import (
    String, Text, Integer,Enum as SQLAlchemyEnum, ForeignKey,JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel
from .user import UserModel, DepartmentModel


class CandidateStatusEnum(str, enum.Enum):
    # 1. 已投递
    APPLICATION = "已投递"
    # 2. AI筛选失败
    AI_FILTER_FAILED = "AI筛选失败"
    # 3. AI筛选成功
    AI_FILTER_PASSED = "AI筛选成功"
    # 4. 待面试
    WAITING_FOR_INTERVIEW = "待面试"
    # 5. 拒绝面试
    REFUSED_INTERVIEW = "拒绝面试"
    # 6. 面试通过
    INTERVIEW_PASSED = "面试通过"
    # 7. 面试未通过
    INTERVIEW_REJECTED = "面试未通过"
    # 8. 已入职
    HIRED = "已入职"
    # 9. 已拒绝
    REJECTED = "已拒绝"


class GenderEnum(str, enum.Enum):
    # 1. 男
    MALE = "男"
    # 2. 女
    FEMALE = "女"
    # 3. 其他
    UNKNOWN = "未知"


class CandidateModel(BaseModel):
    __tablename__ = "candidates"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    gender: Mapped[GenderEnum] = mapped_column(SQLAlchemyEnum(GenderEnum), default=GenderEnum.UNKNOWN, nullable=False)
    birthday: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[str] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    work_experience: Mapped[Optional[str]] = mapped_column(Text)
    project_experience: Mapped[Optional[str]] = mapped_column(Text)
    education_experience: Mapped[Optional[str]] = mapped_column(Text)
    self_evaluation: Mapped[Optional[str]] = mapped_column(Text)
    other_information: Mapped[Optional[str]] = mapped_column(Text)
    skills: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[CandidateStatusEnum] = mapped_column(
        SQLAlchemyEnum(CandidateStatusEnum, values_callable=lambda obj: [e.value for e in obj]),
        default=CandidateStatusEnum.APPLICATION, nullable=False
    )

    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"))
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    # 这条数据是由谁创建的
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    position: Mapped["PositionModel"] = relationship(back_populates="candidates", lazy="joined")
    resume: Mapped["ResumeModel"] = relationship(back_populates="candidate", uselist=False, lazy="joined")
    creator: Mapped["UserModel"] = relationship(lazy="joined")
    ai_score: Mapped["CandidateAIScoreModel"] = relationship(back_populates="candidate", uselist=False)


class CandidateAIScoreModel(BaseModel):
    __tablename__ = "candidate_ai_scores"

    work_experience_score: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_skills_score: Mapped[int] = mapped_column(Integer, nullable=False)
    soft_skills_score: Mapped[int] = mapped_column(Integer, nullable=False)
    educational_background_score: Mapped[int] = mapped_column(Integer, nullable=False)
    project_experience_score: Mapped[int] = mapped_column(Integer, nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    weaknesses: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"))

    candidate: Mapped["CandidateModel"] = relationship(back_populates="ai_score")


class ResumeModel(BaseModel):
    __tablename__ = "resumes"

    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    uploader: Mapped["UserModel"] = relationship()
    candidate: Mapped["CandidateModel"] = relationship(back_populates="resume")