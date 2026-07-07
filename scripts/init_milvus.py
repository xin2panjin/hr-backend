from pymilvus import DataType, MilvusClient

from rag.milvus_client import get_milvus_client
from settings import settings


def create_candidate_profile_collection(client: MilvusClient) -> None:
    """初始化候选人画像 Collection。

    第一阶段采用“一名候选人一条向量”的设计：
    - Milvus 只存脱敏画像和过滤字段；
    - 候选人详情仍以 PostgreSQL 为准；
    - 手机号、邮箱、生日、原始简历文件不写入 Milvus。
    """
    collection_name = settings.MILVUS_CANDIDATE_COLLECTION

    if client.has_collection(collection_name):
        print(f"Collection already exists: {collection_name}")
        return

    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
    )

    schema.add_field(
        field_name="candidate_id",
        datatype=DataType.VARCHAR,
        is_primary=True,
        max_length=64,
    )
    schema.add_field(
        field_name="profile_text",
        datatype=DataType.VARCHAR,
        max_length=8192,
    )
    schema.add_field(
        field_name="dense_vector",
        datatype=DataType.FLOAT_VECTOR,
        dim=settings.MILVUS_CANDIDATE_VECTOR_DIM,
    )
    schema.add_field(
        field_name="department_id",
        datatype=DataType.VARCHAR,
        max_length=64,
    )
    schema.add_field(
        field_name="position_id",
        datatype=DataType.VARCHAR,
        max_length=64,
    )
    schema.add_field(
        field_name="creator_id",
        datatype=DataType.VARCHAR,
        max_length=64,
    )
    schema.add_field(
        field_name="status",
        datatype=DataType.VARCHAR,
        max_length=32,
    )
    schema.add_field(
        field_name="profile_version",
        datatype=DataType.INT64,
    )
    schema.add_field(
        field_name="embedding_model",
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name="updated_at",
        datatype=DataType.INT64,
    )

    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name="dense_vector",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )

    print(f"Collection created: {collection_name}")


def main() -> None:
    client = get_milvus_client()
    create_candidate_profile_collection(client)


if __name__ == "__main__":
    main()