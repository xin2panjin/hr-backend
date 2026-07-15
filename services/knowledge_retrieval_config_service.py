"""知识库检索策略的读取和更新服务。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge.recruiting_policy import (
    DEFAULT_RECRUITING_POLICY_RETRIEVAL_CONFIG,
)
from models.knowledge import KnowledgeBaseModel, KnowledgeBaseStatusEnum
from schemas.knowledge_schema import KnowledgeRetrievalConfigSchema


class KnowledgeRetrievalConfigNotFoundError(ValueError):
    """知识库不存在或已归档。"""


class KnowledgeRetrievalConfigService:
    """以数据库中的知识库级配置作为检索运行时唯一策略来源。"""

    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def get_config(self, *, knowledge_base_key: str) -> KnowledgeRetrievalConfigSchema:
        """读取配置；兼容历史记录中尚未保存的新字段。"""

        knowledge_base = await self._get_active_knowledge_base(knowledge_base_key)
        return KnowledgeRetrievalConfigSchema.model_validate(
            {
                **DEFAULT_RECRUITING_POLICY_RETRIEVAL_CONFIG,
                **dict(knowledge_base.retrieval_config or {}),
            }
        )

    async def update_config(
        self,
        *,
        knowledge_base_key: str,
        config: KnowledgeRetrievalConfigSchema,
    ) -> KnowledgeRetrievalConfigSchema:
        """保存已校验的完整策略，供随后每一次检索立即读取。"""

        knowledge_base = await self._get_active_knowledge_base(knowledge_base_key)
        knowledge_base.retrieval_config = config.model_dump()
        return config

    async def _get_active_knowledge_base(self, knowledge_base_key: str) -> KnowledgeBaseModel:
        knowledge_base = await self.session.scalar(
            select(KnowledgeBaseModel).where(
                KnowledgeBaseModel.key == knowledge_base_key,
                KnowledgeBaseModel.status == KnowledgeBaseStatusEnum.ACTIVE,
            )
        )
        if knowledge_base is None:
            raise KnowledgeRetrievalConfigNotFoundError(
                f"未找到可用知识库：{knowledge_base_key}"
            )
        return knowledge_base
