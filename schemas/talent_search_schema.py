from pydantic import BaseModel, Field

from models.candidate import CandidateStatusEnum


class TalentSearchRequestSchema(BaseModel):
    query: str = Field(..., description="自然语言检索条件")
    top_k: int = Field(10, ge=1, le=50, description="返回数量")
    position_id: str | None = Field(None, description="职位ID过滤")
    status: CandidateStatusEnum | None = Field(None, description="候选人状态过滤")


class TalentSearchCandidateSchema(BaseModel):
    candidate_id: str
    name: str
    position_title: str | None = None
    status: CandidateStatusEnum | str | None = None
    score: float
    profile_text: str | None = None


class TalentSearchResponseSchema(BaseModel):
    candidates: list[TalentSearchCandidateSchema]