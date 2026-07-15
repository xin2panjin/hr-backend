"""HR 助手的企业制度知识检索工具。"""

import json

from langchain.tools import ToolRuntime, tool
from loguru import logger

from iam.permissions import PermissionCode
from models import AsyncSessionFactory
from repository.iam_repo import IamRepo
from repository.user_repo import UserRepo
from services.knowledge_search_service import KnowledgeSearchService
from services.knowledge_retrieval_config_service import KnowledgeRetrievalConfigService
from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition

from ..state import HRAssistantState


async def _load_authorized_user(session, user_id: str):
    """重新加载用户并校验招聘助手权限，避免信任可变的 Graph state。"""

    user = await UserRepo(session).get_by_id(user_id)
    if not user:
        return None, "当前用户不存在，无法检索企业制度。"
    user_roles = await IamRepo(session).get_active_user_roles(user.id)
    has_permission = any(
        PermissionCode.ASSISTANT_USE.value
        in {permission.code for permission in user_role.role.permissions}
        for user_role in user_roles
    )
    if not has_permission:
        return None, "当前用户没有使用企业制度知识库的权限。"
    return user, None


def _build_knowledge_sources_payload(result) -> dict:
    """将检索结果转换为模型可理解且前端可复用的来源 artifact。"""

    return {
        "artifact_type": "knowledge_sources",
        "knowledge_base_key": result.knowledge_base_key,
        "retrieval_mode": result.retrieval_mode.value,
        "trace_id": result.trace_id,
        "sources": [source.to_dict() for source in result.sources],
        "count": len(result.sources),
    }


@tool
async def search_recruiting_knowledge(
    query: str,
    runtime: ToolRuntime[HRAssistantState],
    top_k: int = 5,
    retrieval_mode: str | None = None,
) -> str:
    """检索企业制度知识库，并返回带来源的证据片段。

    参数：
    - query：候选人或 HR 的制度问题，例如“年假如何计算”
    - top_k：最多返回的来源数量
    - retrieval_mode：可选 dense、sparse 或 hybrid
    """

    if not 1 <= top_k <= 20:
        return "检索数量必须在 1 到 20 之间。"
    if retrieval_mode and retrieval_mode not in {"dense", "sparse", "hybrid"}:
        return "retrieval_mode 只能是 dense、sparse 或 hybrid。"

    current_user_id = runtime.state["current_user_id"]
    async with AsyncSessionFactory() as session:
        async with session.begin():
            _, error_message = await _load_authorized_user(session, current_user_id)
            retrieval_config = None
            if not error_message:
                retrieval_config = await KnowledgeRetrievalConfigService(
                    session=session
                ).get_config(knowledge_base_key="recruiting_policy")
        if error_message:
            return error_message

        logger.info(
            "调用制度知识检索工具 user_id={} query_length={} top_k={} mode={}",
            current_user_id,
            len(query.strip()),
            top_k,
            retrieval_mode or "default",
        )
        result = await KnowledgeSearchService(
            knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(
                retrieval_config=retrieval_config.model_dump() if retrieval_config else None
            ),
        ).search(
            query=query,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )

    payload = _build_knowledge_sources_payload(result)
    logger.info(
        "制度知识检索工具完成 user_id={} trace_id={} source_count={}",
        current_user_id,
        result.trace_id,
        len(result.sources),
    )
    return json.dumps(payload, ensure_ascii=False)
