"""HR 企业制度知识库的静态定义。

本模块只描述制度知识库的 Collection 字段与默认检索策略；访问权限、
文档管理和问答产物会在后续业务 Service 中实现。
"""

from typing import Any, Mapping

from pymilvus import DataType

from rag.knowledge_base_definitions import KnowledgeBaseDefinition
from rag.milvus_schema import MilvusHybridCollectionDefinition, MilvusScalarField
from settings import settings


RECRUITING_POLICY_KNOWLEDGE_BASE_KEY = "recruiting_policy"


# 首次注册与历史记录缺失字段时使用的默认检索策略。运行时的实际策略由
# knowledge_bases.retrieval_config 保存，并通过管理页面调整。
DEFAULT_RECRUITING_POLICY_RETRIEVAL_CONFIG = {
    "retrieval_mode": "hybrid",
    "dense_recall_k": 20,
    "sparse_recall_k": 20,
    "hybrid_limit": 20,
    "rrf_k": 60,
    "rerank_enabled": False,
    "rerank_top_k": 5,
    "minimum_evidence_score": 0.3,
    "max_chunks_per_document": 2,
    "merge_adjacent_chunks": True,
}


def build_recruiting_policy_knowledge_base_definition(
    *,
    retrieval_config: Mapping[str, Any] | None = None,
) -> KnowledgeBaseDefinition:
    """构造企业制度知识库的固定注册定义。

    字段均为后续检索、引用展示或后端权限预过滤所需的最小集合；原文件、
    全量正文和任务异常信息只保存在 PostgreSQL 或文件存储，不进入 Milvus。
    """

    collection_definition = MilvusHybridCollectionDefinition(
        collection_name=settings.MILVUS_RECRUITING_POLICY_COLLECTION,
        primary_key_field="id",
        text_field="content",
        vector_dim=settings.MILVUS_KNOWLEDGE_VECTOR_DIM,
        metadata_fields=(
            MilvusScalarField("knowledge_base_id", DataType.VARCHAR, max_length=100),
            MilvusScalarField("document_id", DataType.VARCHAR, max_length=100),
            MilvusScalarField("title", DataType.VARCHAR, max_length=200),
            MilvusScalarField("category", DataType.VARCHAR, max_length=64),
            MilvusScalarField("version", DataType.VARCHAR, max_length=64),
            MilvusScalarField("effective_date", DataType.VARCHAR, max_length=32),
            MilvusScalarField("visibility_scope", DataType.VARCHAR, max_length=64),
            MilvusScalarField("section_path", DataType.VARCHAR, max_length=512),
            MilvusScalarField("page_number", DataType.INT64),
            MilvusScalarField("chunk_index", DataType.INT64),
            MilvusScalarField("chunk_version", DataType.INT64),
        ),
    )
    return KnowledgeBaseDefinition(
        key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
        name="企业制度知识库",
        collection_definition=collection_definition,
        schema_version=1,
        # 静态定义提供默认值；运行时覆盖值来自经后端校验的数据库配置。
        retrieval_config={
            **DEFAULT_RECRUITING_POLICY_RETRIEVAL_CONFIG,
            **dict(retrieval_config or {}),
        },
    )
