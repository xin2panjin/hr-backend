"""初始化企业制度知识库的 PostgreSQL 注册记录与 Milvus Collection。"""

import asyncio

from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition
from models import AsyncSessionFactory
from rag.milvus_client import get_milvus_client
from services.knowledge_base_registry_service import KnowledgeBaseRegistryService


async def initialize_recruiting_policy_knowledge_base() -> None:
    """执行一次可重复运行的企业制度知识库基础设施初始化。"""

    definition = build_recruiting_policy_knowledge_base_definition()
    milvus_client = get_milvus_client()
    registry_service = KnowledgeBaseRegistryService()

    async with AsyncSessionFactory() as session:
        async with session.begin():
            result = await registry_service.ensure_registered(
                session=session,
                milvus_client=milvus_client,
                definition=definition,
            )

    print(
        "企业制度知识库初始化完成："
        f"key={result.key}, collection={result.collection_name}, "
        f"collection_created={result.collection_created}, "
        f"database_record_created={result.database_record_created}"
    )


def main() -> None:
    """脚本入口。"""

    asyncio.run(initialize_recruiting_policy_knowledge_base())


if __name__ == "__main__":
    main()
