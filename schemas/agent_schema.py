from pydantic import BaseModel, Field, ConfigDict
from models.candidate import GenderEnum


class AgentCandidateSchema(BaseModel):
    name: str|None = Field(None, description="候选人姓名")
    gender: GenderEnum = Field(GenderEnum.UNKNOWN, description="候选人性别")
    birthday: str | None = Field(None, description="候选人出生日期，如果只有年份，那么就把日期设置为1月1日")
    email: str|None = Field(None, description="候选人邮箱")
    phone_number: str | None = Field(None, description="候选人电话")
    work_experience: str | None = Field(None, description="候选人工作经历")
    project_experience: str | None = Field(None, description="候选人项目经历")
    education_experience: str | None = Field(None, description="候选人教育经历")
    self_evaluation: str | None = Field(None, description="候选人自我评价")
    other_information: str | None = Field(None, description="候选人其他信息")
    skills: str | None = Field(None, description="候选人技能")

    model_config = ConfigDict(from_attributes=True)


class AgentCandidateScoreSchema(BaseModel):
    """"
    候选人与对应职位得分情况，为int类型的则表示得分值，范围再1-10之间，整形，不要出现不能转化为整形的字符串。
    """
    work_experience_score: int = Field(..., description="工作经验匹配度得分", ge=1, le=10)
    technical_skills_score: int = Field(..., description="技术技能匹配度得分", ge=1, le=10)
    soft_skills_score: int = Field(..., description="软技能潜力得分", ge=1, le=10)
    educational_background_score: int = Field(..., description="教育背景得分", ge=1, le=10)
    project_experience_score: int = Field(..., description="项目经验匹配度得分", ge=1, le=10)
    overall_score: int = Field(..., description="总分", ge=1, le=10)
    summary: str = Field(..., description="总结")
    strengths: list[str] = Field(..., description="优点")
    weaknesses: list[str] = Field(..., description="缺点")