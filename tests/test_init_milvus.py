import json

from scripts.init_milvus import create_candidate_profile_collection
from settings import settings


class FakeMilvusClient:
    """替代真实 Milvus，仅验证初始化时提交的 Schema 和索引参数。"""

    def __init__(self, existing_collections: set[str] | None = None):
        self.existing_collections = existing_collections or set()
        self.create_calls: list[dict] = []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.existing_collections

    def create_collection(self, **kwargs) -> None:
        self.create_calls.append(kwargs)


def test_create_candidate_profile_collection_builds_bm25_schema():
    client = FakeMilvusClient()

    create_candidate_profile_collection(client)

    assert len(client.create_calls) == 1

    create_call = client.create_calls[0]
    assert create_call["collection_name"] == settings.MILVUS_CANDIDATE_COLLECTION

    schema = create_call["schema"].to_dict()
    fields = {field["name"]: field for field in schema["fields"]}

    assert fields["dense_vector"]["type"].name == "FLOAT_VECTOR"
    assert fields["sparse_vector"]["type"].name == "SPARSE_FLOAT_VECTOR"
    assert fields["sparse_vector"]["is_function_output"] is True
    assert fields["profile_text"]["params"]["enable_analyzer"] is True
    assert json.loads(fields["profile_text"]["params"]["analyzer_params"]) == {
        "tokenizer": "jieba",
    }

    functions = schema["functions"]
    assert len(functions) == 1
    assert functions[0]["name"] == "profile_text_bm25"
    assert functions[0]["input_field_names"] == ["profile_text"]
    assert functions[0]["output_field_names"] == ["sparse_vector"]
    assert functions[0]["type"].name == "BM25"

    # pymilvus 返回 IndexParam 对象，统一转为字典后再断言。
    indexes = {
        index.field_name: index.to_dict()
        for index in create_call["index_params"]
    }
    dense_index = indexes["dense_vector"]
    sparse_index = indexes["sparse_vector"]

    assert dense_index["metric_type"] == "COSINE"
    assert sparse_index["index_type"] == "SPARSE_INVERTED_INDEX"
    assert sparse_index["metric_type"] == "BM25"


def test_create_candidate_profile_collection_skips_existing_collection():
    client = FakeMilvusClient(
        existing_collections={settings.MILVUS_CANDIDATE_COLLECTION},
    )

    create_candidate_profile_collection(client)

    assert client.create_calls == []