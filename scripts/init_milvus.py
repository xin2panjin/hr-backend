from pymilvus import DataType, MilvusClient
from rag.milvus_client import get_milvus_client
from rag.milvus_schema import (
    MilvusHybridCollectionDefinition,
    MilvusScalarField,
    create_hybrid_collection,
)
from settings import settings


def build_candidate_profile_collection_definition() -> MilvusHybridCollectionDefinition:
    """构造候选人画像 Collection 定义，保留候选人专属字段。"""

    return MilvusHybridCollectionDefinition(
        collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
        primary_key_field="candidate_id",
        text_field="profile_text",
        vector_dim=settings.MILVUS_CANDIDATE_VECTOR_DIM,
        metadata_fields=(
            MilvusScalarField("department_id", DataType.VARCHAR, max_length=64),
            MilvusScalarField("position_id", DataType.VARCHAR, max_length=64),
            MilvusScalarField("creator_id", DataType.VARCHAR, max_length=64),
            MilvusScalarField("status", DataType.VARCHAR, max_length=32),
            MilvusScalarField("profile_version", DataType.INT64),
            MilvusScalarField("embedding_model", DataType.VARCHAR, max_length=128),
            MilvusScalarField("updated_at", DataType.INT64),
        ),
    )


def create_candidate_profile_collection(client: MilvusClient) -> None:
    """初始化支持稠密向量和 BM25 的候选人画像 Collection。

    - dense_vector：用于语义检索；
    - sparse_vector：由 Milvus BM25 Function 自动生成，用于关键词检索；
    - profile_text：只保存脱敏后的候选人画像，不保存联系方式等敏感信息。
    """

    definition = build_candidate_profile_collection_definition()
    if create_hybrid_collection(client, definition):
        print(f"Collection created: {definition.collection_name}")
    else:
        print(f"Collection already exists: {definition.collection_name}")

def main() -> None:
    """初始化Collection，可重复执行。"""

    client = get_milvus_client()
    create_candidate_profile_collection(client)


if __name__ == "__main__":
    main()
