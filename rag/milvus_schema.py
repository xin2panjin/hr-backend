"""Milvus Dense + BM25 Collection 的通用建表工厂。"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from pymilvus import DataType, Function, FunctionType, MilvusClient


@dataclass(frozen=True, slots=True)
class MilvusScalarField:
    """Collection 中除主键、文本和向量外的可过滤元数据字段。"""

    field_name: str
    datatype: DataType
    max_length: int | None = None

    def __post_init__(self) -> None:
        if not self.field_name.strip():
            raise ValueError("field_name 不能为空")
        if self.max_length is not None and self.max_length < 1:
            raise ValueError("max_length 必须大于 0")

    def to_add_field_kwargs(self) -> dict[str, Any]:
        """转换为 Pymilvus Schema.add_field 所需参数。"""

        kwargs: dict[str, Any] = {
            "field_name": self.field_name,
            "datatype": self.datatype,
        }
        if self.max_length is not None:
            kwargs["max_length"] = self.max_length
        return kwargs


@dataclass(frozen=True, slots=True)
class MilvusHybridCollectionDefinition:
    """创建一个 Dense + Milvus BM25 Collection 所需的静态定义。

    定义只允许由后端代码构造。它约束 Collection 的字段、分词器和索引，
    不包含业务权限，也不接收接口层传入的任意字段或 Collection 名称。
    """

    collection_name: str
    primary_key_field: str
    text_field: str
    vector_dim: int
    metadata_fields: tuple[MilvusScalarField, ...] = ()
    primary_key_max_length: int = 64
    text_max_length: int = 8192
    dense_vector_field: str = "dense_vector"
    sparse_vector_field: str = "sparse_vector"
    text_analyzer_params: Mapping[str, Any] = field(
        default_factory=lambda: {"tokenizer": "jieba"}
    )
    dense_metric_type: str = "COSINE"
    sparse_index_params: Mapping[str, Any] = field(
        default_factory=lambda: {
            "inverted_index_algo": "DAAT_MAXSCORE",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
        }
    )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("collection_name", self.collection_name),
            ("primary_key_field", self.primary_key_field),
            ("text_field", self.text_field),
            ("dense_vector_field", self.dense_vector_field),
            ("sparse_vector_field", self.sparse_vector_field),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} 不能为空")
        if self.vector_dim < 1:
            raise ValueError("vector_dim 必须大于 0")
        if self.primary_key_max_length < 1 or self.text_max_length < 1:
            raise ValueError("字段最大长度必须大于 0")

        field_names = [
            self.primary_key_field,
            self.text_field,
            self.dense_vector_field,
            self.sparse_vector_field,
            *(item.field_name for item in self.metadata_fields),
        ]
        if len(set(field_names)) != len(field_names):
            raise ValueError("Collection 字段名不能重复")

        object.__setattr__(self, "text_analyzer_params", dict(self.text_analyzer_params))
        object.__setattr__(self, "sparse_index_params", dict(self.sparse_index_params))

    @property
    def bm25_function_name(self) -> str:
        """以文本字段生成稳定的 BM25 Function 名称。"""

        return f"{self.text_field}_bm25"


def create_hybrid_collection(
    client: MilvusClient,
    definition: MilvusHybridCollectionDefinition,
) -> bool:
    """按定义创建 Dense + BM25 Collection。

    返回 ``True`` 表示本次新建，返回 ``False`` 表示 Collection 已存在。
    线上请求不得调用本函数；它只应由初始化命令或部署阶段任务执行。
    """

    if client.has_collection(definition.collection_name):
        return False

    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
    )
    schema.add_field(
        field_name=definition.primary_key_field,
        datatype=DataType.VARCHAR,
        is_primary=True,
        max_length=definition.primary_key_max_length,
    )
    schema.add_field(
        field_name=definition.text_field,
        datatype=DataType.VARCHAR,
        max_length=definition.text_max_length,
        enable_analyzer=True,
        analyzer_params=dict(definition.text_analyzer_params),
    )
    schema.add_field(
        field_name=definition.dense_vector_field,
        datatype=DataType.FLOAT_VECTOR,
        dim=definition.vector_dim,
    )
    schema.add_field(
        field_name=definition.sparse_vector_field,
        datatype=DataType.SPARSE_FLOAT_VECTOR,
    )
    for metadata_field in definition.metadata_fields:
        schema.add_field(**metadata_field.to_add_field_kwargs())

    # Milvus 在写入文本字段时自动生成稀疏向量；应用层不应自行写入它。
    schema.add_function(
        Function(
            name=definition.bm25_function_name,
            input_field_names=[definition.text_field],
            output_field_names=[definition.sparse_vector_field],
            function_type=FunctionType.BM25,
        )
    )

    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=definition.dense_vector_field,
        index_type="AUTOINDEX",
        metric_type=definition.dense_metric_type,
    )
    index_params.add_index(
        field_name=definition.sparse_vector_field,
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params=dict(definition.sparse_index_params),
    )
    client.create_collection(
        collection_name=definition.collection_name,
        schema=schema,
        index_params=index_params,
    )
    return True
