"""受后端控制的知识库静态定义契约。"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from rag.milvus_schema import MilvusHybridCollectionDefinition


@dataclass(frozen=True, slots=True)
class KnowledgeBaseDefinition:
    """一个知识库注册到 PostgreSQL 与 Milvus 前必须具备的静态信息。

    该定义只能由后端业务模块构造，避免 API、前端或 LLM 任意指定
    Collection 名称、字段结构和检索阈值。
    """

    key: str
    name: str
    collection_definition: MilvusHybridCollectionDefinition
    schema_version: int
    retrieval_config: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("知识库 key 不能为空")
        if not self.name.strip():
            raise ValueError("知识库名称不能为空")
        if self.schema_version < 1:
            raise ValueError("schema_version 必须大于 0")

        # 调用方不应在运行过程中修改已注册定义的检索参数。
        object.__setattr__(
            self,
            "retrieval_config",
            MappingProxyType(dict(self.retrieval_config)),
        )

    @property
    def collection_name(self) -> str:
        """返回该知识库唯一对应的 Milvus Collection 名称。"""

        return self.collection_definition.collection_name
