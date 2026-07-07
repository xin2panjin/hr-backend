import json

from langchain.tools import ToolRuntime, tool

from models import AsyncSessionFactory
from models.candidate import CandidateStatusEnum
from repository.candidate_repo import CandidateRepo
from repository.user_repo import UserRepo
from services.talent_search_service import TalentSearchService

from ..state import HRAssistantState


def _parse_status(status: str | None) -> CandidateStatusEnum | None:
    """把模型传入的状态文本转换为候选人状态枚举。"""

    if not status:
        return None

    for item in CandidateStatusEnum:
        if status == item.value or status == item.name:
            return item

    return None


@tool
async def search_talent_pool(
    query: str,
    runtime: ToolRuntime[HRAssistantState],
    top_k: int = 3,
    position_id: str | None = None,
    status: str | None = None,
) -> str:
    """根据自然语言条件检索人才库候选人。

    参数：
    - query: 用户的人才检索需求，例如“找一个熟悉 Python 和大模型应用的人”
    - top_k: 返回候选人数量，默认10
    - position_id: 可选，指定职位ID过滤
    - status: 可选，候选人状态中文值，例如“已投递”“AI筛选通过”
    """

    current_user_id = runtime.state["current_user_id"]

    async with AsyncSessionFactory() as session:
        async with session.begin():
            user = await UserRepo(session).get_by_id(current_user_id)
            if not user:
                return "当前用户不存在，无法检索人才库。"

            service = TalentSearchService(
                candidate_repo=CandidateRepo(session),
            )
            candidates = await service.search(
                query=query,
                current_user=user,
                top_k=top_k,
                position_id=position_id,
                status=_parse_status(status),
            )

    if not candidates:
        return "没有找到符合条件的候选人。"

    return json.dumps(
        {
            "candidates": candidates,
            "count": len(candidates),
        },
        ensure_ascii=False,
        default=str,
    )