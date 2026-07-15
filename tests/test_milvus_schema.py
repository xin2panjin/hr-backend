import json

import pytest
from pymilvus import DataType

from rag.milvus_schema import (
    MilvusHybridCollectionDefinition,
    MilvusScalarField,
    create_hybrid_collection,
)


class FakeMilvusClient:
    """替代真实 Milvus，验证通用建表工厂提交的参数。"""

    def __init__(self, existing_collections: set[str] | None = None):
        self.existing_collections = existing_collections or set()
        self.create_calls: list[dict] = []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.existing_collections

    def create_collection(self, **kwargs) -> None:
        self.create_calls.append(kwargs)


def build_knowledge_definition() -> MilvusHybridCollectionDefinition:
    """使用不同于候选人画像的字段验证工厂通用性。"""

    return MilvusHybridCollectionDefinition(
        collection_name="recruiting_policy_chunks_v1",
        primary_key_field="chunk_id",
        text_field="content",
        vector_dim=4,
        metadata_fields=(
            MilvusScalarField("document_id", DataType.VARCHAR, max_length=64),
            MilvusScalarField("page_number", DataType.INT64),
        ),
    )


def test_create_hybrid_collection_builds_custom_dense_bm25_schema():
    client = FakeMilvusClient()

    created = create_hybrid_collection(client, build_knowledge_definition())

    assert created is True
    create_call = client.create_calls[0]
    assert create_call["collection_name"] == "recruiting_policy_chunks_v1"

    schema = create_call["schema"].to_dict()
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["chunk_id"]["is_primary"] is True
    assert fields["content"]["params"]["enable_analyzer"] is True
    assert json.loads(fields["content"]["params"]["analyzer_params"]) == {
        "tokenizer": "jieba"
    }
    assert fields["dense_vector"]["type"].name == "FLOAT_VECTOR"
    assert fields["sparse_vector"]["is_function_output"] is True
    assert fields["document_id"]["params"]["max_length"] == 64

    function = schema["functions"][0]
    assert function["name"] == "content_bm25"
    assert function["input_field_names"] == ["content"]
    assert function["output_field_names"] == ["sparse_vector"]

    indexes = {
        index.field_name: index.to_dict()
        for index in create_call["index_params"]
    }
    assert indexes["dense_vector"]["metric_type"] == "COSINE"
    assert indexes["sparse_vector"]["index_type"] == "SPARSE_INVERTED_INDEX"


def test_create_hybrid_collection_skips_existing_collection():
    definition = build_knowledge_definition()
    client = FakeMilvusClient(existing_collections={definition.collection_name})

    created = create_hybrid_collection(client, definition)

    assert created is False
    assert client.create_calls == []


def test_hybrid_collection_definition_rejects_duplicate_field_names():
    with pytest.raises(ValueError, match="字段名不能重复"):
        MilvusHybridCollectionDefinition(
            collection_name="invalid",
            primary_key_field="id",
            text_field="content",
            vector_dim=4,
            metadata_fields=(MilvusScalarField("content", DataType.VARCHAR, 64),),
        )
