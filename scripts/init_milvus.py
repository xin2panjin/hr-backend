from pymilvus import DataType, Function, FunctionType, MilvusClient
from rag.milvus_client import get_milvus_client
from settings import settings

def create_candidate_profile_collection(client: MilvusClient) -> None:
    """初始化支持稠密向量和 BM25 的候选人画像 Collection。

    - dense_vector：用于语义检索；
    - sparse_vector：由 Milvus BM25 Function 自动生成，用于关键词检索；
    - profile_text：只保存脱敏后的候选人画像，不保存联系方式等敏感信息。
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
        # 简历画像以中文为主，使用 jieba 分词，为 BM25 建立倒排索引。
        enable_analyzer=True,
        analyzer_params={"tokenizer": "jieba"},
    )
    schema.add_field(
        field_name="dense_vector",
        datatype=DataType.FLOAT_VECTOR,
        dim=settings.MILVUS_CANDIDATE_VECTOR_DIM,
    )
    schema.add_field(
        field_name="sparse_vector",
        datatype=DataType.SPARSE_FLOAT_VECTOR,
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

    # Milvus 在写入 profile_text 时自动生成 sparse_vector；
    # 应用层后续不应自行计算或写入 sparse_vector。
    schema.add_function(
        Function(
            name="profile_text_bm25",
            input_field_names=["profile_text"],
            output_field_names=["sparse_vector"],
            function_type=FunctionType.BM25,
        )
    )

    index_params = MilvusClient.prepare_index_params()

    # 稠密向量：与 v1 保持一致，用于语义相似度检索。
    index_params.add_index(
        field_name="dense_vector",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    # 稀疏向量：BM25 检索使用倒排索引。
    index_params.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={
            "inverted_index_algo": "DAAT_MAXSCORE",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
        },
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )

    print(f"Collection created: {collection_name}")

def main() -> None:
    """初始化Collection，可重复执行。"""

    client = get_milvus_client()
    create_candidate_profile_collection(client)


if __name__ == "__main__":
    main()