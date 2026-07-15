"""知识库注册服务：协调静态定义、Milvus Collection 和数据库注册表。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge import KnowledgeBaseModel, KnowledgeBaseStatusEnum
from rag.knowledge_base_definitions import KnowledgeBaseDefinition
from rag.milvus_schema import create_hybrid_collection


@dataclass(frozen=True, slots=True)
class KnowledgeBaseRegistrationResult:
    """一次知识库初始化的幂等执行结果。"""

    key: str
    collection_name: str
    collection_created: bool
    database_record_created: bool


class KnowledgeBaseRegistryService:
    """把受后端控制的知识库定义注册到两类基础设施中。"""

    async def ensure_registered(
        self,
        *,
        session: AsyncSession,
        milvus_client,
        definition: KnowledgeBaseDefinition,
    ) -> KnowledgeBaseRegistrationResult:
        """确保 Collection 和 ``knowledge_bases`` 记录都存在。

        方法可安全重复执行。已经存在的注册记录必须与代码定义保持相同索引
        结构；检索策略由数据库运行时配置管理，不属于静态结构校验范围。
        """

        collection_created = create_hybrid_collection(
            milvus_client,
            definition.collection_definition,
        )
        knowledge_base = await session.scalar(
            select(KnowledgeBaseModel).where(KnowledgeBaseModel.key == definition.key)
        )
        if knowledge_base is None:
            session.add(
                KnowledgeBaseModel(
                    key=definition.key,
                    name=definition.name,
                    collection_name=definition.collection_name,
                    schema_version=definition.schema_version,
                    status=KnowledgeBaseStatusEnum.ACTIVE,
                    retrieval_config=dict(definition.retrieval_config),
                )
            )
            database_record_created = True
        else:
            self._validate_existing_registration(knowledge_base, definition)
            database_record_created = False

        return KnowledgeBaseRegistrationResult(
            key=definition.key,
            collection_name=definition.collection_name,
            collection_created=collection_created,
            database_record_created=database_record_created,
        )

    @staticmethod
    def _validate_existing_registration(
        knowledge_base: KnowledgeBaseModel,
        definition: KnowledgeBaseDefinition,
    ) -> None:
        """校验已有注册记录没有偏离代码定义的索引结构。"""

        expected_values = {
            "collection_name": definition.collection_name,
            "schema_version": definition.schema_version,
        }
        mismatches = [
            field_name
            for field_name, expected_value in expected_values.items()
            if getattr(knowledge_base, field_name) != expected_value
        ]
        if mismatches:
            raise ValueError(
                f"知识库 {definition.key} 的已有注册记录与代码定义不一致："
                f"{', '.join(mismatches)}"
            )
