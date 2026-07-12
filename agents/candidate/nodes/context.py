from dataclasses import dataclass
from typing import Any

from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from repository.user_repo import UserRepo
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema


@dataclass(frozen=True)
class CandidateRuntimeContext:
    """候选人流程节点运行时需要的业务上下文。

    该对象只在当前节点执行期间使用，不写回 LangGraph checkpoint。
    """

    candidate: CandidateSchema
    position: PositionSchema
    interviewer: UserSchema


def get_state_value(state: Any, field_name: str) -> Any:
    """兼容 dict 和 Pydantic state，读取轻量流程字段。"""
    if isinstance(state, dict):
        return state.get(field_name)
    return getattr(state, field_name, None)


async def load_candidate_runtime_context(state: Any) -> CandidateRuntimeContext:
    """根据轻量 State 中的 ID 从数据库加载候选人、职位和面试官上下文。"""
    candidate_id = get_state_value(state, "candidate_id")
    position_id = get_state_value(state, "position_id")
    interviewer_id = get_state_value(state, "interviewer_id")

    if not candidate_id:
        raise ValueError("候选人流程缺少 candidate_id")

    async with AsyncSessionFactory() as session:
        async with session.begin():
            candidate_model = await CandidateRepo(session).get_by_id(candidate_id)
            if not candidate_model:
                raise ValueError(f"候选人不存在：{candidate_id}")

            position_model = candidate_model.position
            if not position_model:
                raise ValueError(f"候选人未关联职位：{candidate_id}")

            if position_id and position_model.id != position_id:
                raise ValueError(
                    "候选人职位与流程状态不一致："
                    f"candidate_id={candidate_id}, "
                    f"state_position_id={position_id}, "
                    f"actual_position_id={position_model.id}"
                )

            interviewer_model = position_model.creator
            if interviewer_id and interviewer_model.id != interviewer_id:
                interviewer_model = await UserRepo(session).get_by_id(interviewer_id)
                if not interviewer_model:
                    raise ValueError(f"面试官不存在：{interviewer_id}")

            return CandidateRuntimeContext(
                candidate=CandidateSchema.model_validate(candidate_model),
                position=PositionSchema.model_validate(position_model),
                interviewer=UserSchema.model_validate(interviewer_model),
            )
