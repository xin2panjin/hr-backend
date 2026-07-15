"""知识库结构化切片与幂等索引任务测试。"""

from types import SimpleNamespace
from datetime import date
from pathlib import Path

import pytest

from models.knowledge import (
    KnowledgeDocumentStatusEnum,
    KnowledgeIndexTaskStatusEnum,
    KnowledgeIndexTaskTypeEnum,
)
from rag.embeddings import EmbeddingService
from rag.knowledge_base_definitions import KnowledgeBaseDefinition
from rag.milvus_schema import MilvusHybridCollectionDefinition
from services.knowledge_index_service import (
    KnowledgeIndexService,
    StructuredKnowledgeChunker,
)
from services.knowledge_text_processing import (
    KnowledgeChunkingStrategy,
    KnowledgeTextProcessingConfig,
)
from services.knowledge_text_extractor import ExtractedTextBlock


class FakeSession:
    """覆盖幂等任务登记的最小数据库会话。"""

    def __init__(self, existing_task=None):
        self.existing_task = existing_task
        self.added_models: list[object] = []

    async def scalar(self, statement):
        return self.existing_task

    def add(self, model) -> None:
        self.added_models.append(model)

    async def flush(self, models) -> None:
        for model in models:
            if getattr(model, "id", None) is None:
                model.id = "task-1"


class FakeExecutionSession:
    """模拟索引执行期间使用的数据库会话。"""

    def __init__(self, task=None, pending_tasks=None):
        self.task = task
        self.pending_tasks = pending_tasks or []
        self.added_models: list[object] = []
        self.executed_statements: list[object] = []
        self.flush_count = 0

    async def scalar(self, statement):
        return self.task

    async def scalars(self, statement):
        return self.pending_tasks

    def add(self, model) -> None:
        self.added_models.append(model)

    async def execute(self, statement) -> None:
        self.executed_statements.append(statement)

    async def flush(self, models) -> None:
        self.flush_count += 1
        for model in models:
            if getattr(model, "id", None) is None:
                model.id = f"chunk-{len(self.added_models)}"


class FakeTextExtractor:
    def __init__(self, blocks):
        self.blocks = blocks
        self.calls: list[tuple[Path, str]] = []

    def extract(self, *, file_path, file_type):
        self.calls.append((Path(file_path), file_type))
        return self.blocks


class FakeEmbeddingService:
    model = "fake-embedding-v1"

    def __init__(self, vectors):
        self.vectors = vectors
        self.received_texts: list[list[str]] = []

    async def embed_documents(self, texts):
        self.received_texts.append(texts)
        return self.vectors


class FakeMilvusClient:
    def __init__(self):
        self.delete_calls: list[dict] = []
        self.upsert_calls: list[dict] = []

    def delete(self, **kwargs) -> None:
        self.delete_calls.append(kwargs)

    def upsert(self, **kwargs) -> None:
        self.upsert_calls.append(kwargs)


def build_document(content_hash: str = "a" * 64):
    return SimpleNamespace(
        id="document-1",
        knowledge_base_id="knowledge-base-1",
        content_hash=content_hash,
    )


def build_execution_definition() -> KnowledgeBaseDefinition:
    return KnowledgeBaseDefinition(
        key="test_policy",
        name="测试制度知识库",
        collection_definition=MilvusHybridCollectionDefinition(
            collection_name="test_policy_chunks_v1",
            primary_key_field="id",
            text_field="content",
            vector_dim=3,
            metadata_fields=(),
        ),
        schema_version=1,
        retrieval_config={},
    )


def build_execution_task(task_type=KnowledgeIndexTaskTypeEnum.UPSERT):
    definition = build_execution_definition()
    knowledge_base = SimpleNamespace(
        id="knowledge-base-1",
        key=definition.key,
        collection_name=definition.collection_name,
        schema_version=definition.schema_version,
    )
    document = SimpleNamespace(
        id="document-1",
        knowledge_base_id=knowledge_base.id,
        storage_path="test_policy/policy.md",
        file_type="md",
        title="员工休假制度",
        category="leave",
        version="V1",
        effective_date=date(2026, 1, 1),
        visibility_scope="hr_only",
        status=KnowledgeDocumentStatusEnum.DRAFT,
        indexed_at=None,
    )
    task = SimpleNamespace(
        id="task-1",
        knowledge_base=knowledge_base,
        document=document,
        task_type=task_type,
        status=KnowledgeIndexTaskStatusEnum.PENDING,
        retry_count=0,
        target_chunk_version=1,
        task_metadata={"source": "test"},
        started_at=None,
        completed_at=None,
        last_error=None,
    )
    return definition, task


def test_structured_chunker_keeps_section_page_and_contextual_content():
    chunker = StructuredKnowledgeChunker(max_characters=60, overlap_characters=10)
    chunks = chunker.chunk(
        document_title="员工休假制度",
        text_blocks=[
            ExtractedTextBlock(
                text="员工申请年假需提前提交申请。" * 5,
                section_path="休假制度 > 年假",
                page_number=1,
            ),
            ExtractedTextBlock(
                text="年假天数根据累计工作年限确定。",
                section_path="休假制度 > 年假",
                page_number=1,
            ),
            ExtractedTextBlock(
                text="病假申请应提供相应证明。",
                section_path="休假制度 > 病假",
                page_number=2,
            ),
        ],
    )

    assert len(chunks) >= 3
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.content.startswith("制度：员工休假制度\n") for chunk in chunks)
    assert chunks[0].section_path == "休假制度 > 年假"
    assert chunks[0].page_number == 1
    assert chunks[-1].section_path == "休假制度 > 病假"
    assert chunks[-1].page_number == 2
    assert all(len(chunk.content_hash) == 64 for chunk in chunks)
    assert all(chunk.token_count > 0 for chunk in chunks)


def test_structured_chunker_rejects_invalid_parameters_and_empty_blocks():
    with pytest.raises(ValueError, match="max_characters"):
        StructuredKnowledgeChunker(max_characters=49)
    with pytest.raises(ValueError, match="overlap_characters"):
        StructuredKnowledgeChunker(max_characters=100, overlap_characters=100)
    with pytest.raises(ValueError, match="空文本块"):
        StructuredKnowledgeChunker().chunk(
            document_title="制度",
            text_blocks=[ExtractedTextBlock(text="  ")],
        )


@pytest.mark.parametrize(
    "strategy",
    [
        KnowledgeChunkingStrategy.STRUCTURED_BUILTIN,
        KnowledgeChunkingStrategy.FIXED_LENGTH,
        KnowledgeChunkingStrategy.CUSTOM_CHARACTER,
        KnowledgeChunkingStrategy.LANGCHAIN_RECURSIVE,
    ],
)
def test_chunker_supports_all_strategies_and_preserves_source_metadata(strategy):
    chunks = StructuredKnowledgeChunker(
        max_characters=60,
        overlap_characters=10,
        strategy=strategy,
        custom_separator="。",
    ).chunk(
        document_title="员工休假制度",
        text_blocks=[
            ExtractedTextBlock(
                text="员工申请年假需提前提交申请。年假天数根据累计工作年限确定。" * 3,
                section_path="休假制度 > 年假",
                page_number=2,
            )
        ],
    )

    assert len(chunks) >= 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.section_path == "休假制度 > 年假" for chunk in chunks)
    assert all(chunk.page_number == 2 for chunk in chunks)
    assert all(chunk.content.startswith("制度：员工休假制度") for chunk in chunks)


def test_processing_config_uses_builtin_strategy_for_legacy_task_metadata():
    config = KnowledgeTextProcessingConfig.from_mapping(
        {"chunking": {"max_characters": 300, "overlap_characters": 30}}
    )

    assert config.chunking.strategy == KnowledgeChunkingStrategy.STRUCTURED_BUILTIN


def test_processing_config_rejects_empty_custom_character_separator():
    with pytest.raises(ValueError, match="custom_separator 不能为空"):
        KnowledgeTextProcessingConfig.from_mapping(
            {
                "chunking": {
                    "strategy": "custom_character",
                    "custom_separator": "",
                }
            }
        )


def test_custom_character_strategy_uses_one_configured_separator():
    first = "甲" * 30 + "|"
    second = "乙" * 30 + "|"
    third = "丙" * 30
    chunker = StructuredKnowledgeChunker(
        max_characters=50,
        overlap_characters=0,
        strategy=KnowledgeChunkingStrategy.CUSTOM_CHARACTER,
        custom_separator="|",
    )

    assert chunker._split_to_chunk_bodies(f"{first}{second}{third}") == [first, second, third]


def test_recursive_strategy_uses_configured_separator_sequence():
    chunker = StructuredKnowledgeChunker(
        max_characters=50,
        overlap_characters=0,
        strategy=KnowledgeChunkingStrategy.LANGCHAIN_RECURSIVE,
        recursive_separators=("|", ""),
    )

    assert chunker._split_to_chunk_bodies("甲" * 30 + "|" + "乙" * 30) == [
        "甲" * 30,
        "|" + "乙" * 30,
    ]


def test_processing_config_replays_legacy_custom_separator_strategy():
    config = KnowledgeTextProcessingConfig.from_mapping(
        {
            "chunking": {
                "strategy": "custom_separator",
                "custom_separators": ["\n\n", "。", ""],
            }
        }
    )

    assert config.chunking.strategy == KnowledgeChunkingStrategy.LEGACY_CUSTOM_SEPARATOR
    assert config.to_dict()["chunking"]["custom_separators"] == ["\n\n", "。", ""]


@pytest.mark.asyncio
async def test_ensure_upsert_task_creates_deterministic_idempotent_task():
    session = FakeSession()
    document = build_document()

    result = await KnowledgeIndexService(session).ensure_upsert_task(document=document)

    assert result.created is True
    task = result.task
    assert task.idempotency_key == KnowledgeIndexService.build_idempotency_key(
        knowledge_base_id="knowledge-base-1",
        document_id="document-1",
        task_type=KnowledgeIndexTaskTypeEnum.UPSERT,
        content_hash="a" * 64,
        target_chunk_version=1,
    )
    assert task.document_id == document.id
    assert task.content_hash == document.content_hash
    assert task.target_chunk_version == 1
    assert task.task_metadata == {
        "source": "document_registration",
        "processing_config": {
            "cleaning": {
                "normalize_whitespace": True,
                "remove_urls_and_emails": False,
                "remove_blockquote_metadata": False,
            },
            "chunking": {
                "max_characters": 500,
                "overlap_characters": 80,
                "strategy": "structured_builtin",
                "custom_separator": "。",
                "recursive_separators": ["\n\n", "\n", "。", "！", "？", "；", ";", "，", ",", " ", ""],
            },
        },
    }


@pytest.mark.asyncio
async def test_ensure_upsert_task_reuses_existing_task_for_same_document_version():
    existing_task = SimpleNamespace(id="task-existing")
    session = FakeSession(existing_task=existing_task)

    result = await KnowledgeIndexService(session).ensure_upsert_task(
        document=build_document(),
    )

    assert result.task is existing_task
    assert result.created is False
    assert session.added_models == []


@pytest.mark.asyncio
async def test_ensure_upsert_task_snapshots_the_selected_processing_config():
    config = KnowledgeTextProcessingConfig.from_mapping(
        {
            "cleaning": {"remove_urls_and_emails": True},
            "chunking": {"max_characters": 300, "overlap_characters": 30},
        }
    )

    task = (
        await KnowledgeIndexService(FakeSession()).ensure_upsert_task(
            document=build_document(),
            processing_config=config,
        )
    ).task

    assert task.task_metadata["processing_config"] == config.to_dict()


def test_index_task_idempotency_key_changes_when_content_or_chunk_version_changes():
    base_kwargs = {
        "knowledge_base_id": "knowledge-base-1",
        "document_id": "document-1",
        "task_type": KnowledgeIndexTaskTypeEnum.UPSERT,
        "content_hash": "a" * 64,
        "target_chunk_version": 1,
    }
    original_key = KnowledgeIndexService.build_idempotency_key(**base_kwargs)
    changed_content_key = KnowledgeIndexService.build_idempotency_key(
        **{**base_kwargs, "content_hash": "b" * 64}
    )
    changed_version_key = KnowledgeIndexService.build_idempotency_key(
        **{**base_kwargs, "target_chunk_version": 2}
    )

    assert original_key != changed_content_key
    assert original_key != changed_version_key


@pytest.mark.asyncio
async def test_process_upsert_task_persists_chunks_and_upserts_milvus(tmp_path):
    definition, task = build_execution_task()
    session = FakeExecutionSession()
    extractor = FakeTextExtractor(
        [
            ExtractedTextBlock(
                text="员工申请年假需提前提交申请。",
                section_path="休假制度 > 年假",
                page_number=1,
            ),
            ExtractedTextBlock(
                text="年假天数根据累计工作年限确定。",
                section_path="休假制度 > 年假",
                page_number=1,
            ),
        ]
    )
    embedding_service = FakeEmbeddingService([[0.1, 0.2, 0.3]])
    milvus_client = FakeMilvusClient()
    service = KnowledgeIndexService(
        session,
        knowledge_base_definition=definition,
        text_extractor=extractor,
        chunker=StructuredKnowledgeChunker(max_characters=500, overlap_characters=80),
        embedding_service=embedding_service,
        milvus_client=milvus_client,
        file_path_resolver=lambda storage_path: tmp_path / storage_path,
    )

    result = await service.process_task(task)

    assert result.succeeded is True
    assert result.chunk_count == 1
    assert task.status == KnowledgeIndexTaskStatusEnum.SUCCEEDED
    assert task.document.status == KnowledgeDocumentStatusEnum.ACTIVE
    assert task.document.indexed_at is not None
    assert task.task_metadata["embedding_model"] == "fake-embedding-v1"
    assert task.task_metadata["chunk_count"] == 1
    assert len(session.added_models) == 1
    assert len(session.executed_statements) == 1
    assert milvus_client.delete_calls == [
        {
            "collection_name": "test_policy_chunks_v1",
            "filter": 'document_id == "document-1"',
        }
    ]
    upsert_row = milvus_client.upsert_calls[0]["data"][0]
    assert upsert_row["id"] == "chunk-1"
    assert upsert_row["document_id"] == "document-1"
    assert upsert_row["page_number"] == 1
    assert upsert_row["dense_vector"] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_process_upsert_task_marks_failed_when_embedding_dimension_is_wrong(tmp_path):
    definition, task = build_execution_task()
    session = FakeExecutionSession()
    service = KnowledgeIndexService(
        session,
        knowledge_base_definition=definition,
        text_extractor=FakeTextExtractor([ExtractedTextBlock(text="制度正文")]),
        embedding_service=FakeEmbeddingService([[0.1, 0.2]]),
        milvus_client=FakeMilvusClient(),
        file_path_resolver=lambda storage_path: tmp_path / storage_path,
    )

    result = await service.process_task(task)

    assert result.succeeded is False
    assert result.error_type == "ValueError"
    assert task.status == KnowledgeIndexTaskStatusEnum.FAILED
    assert task.document.status == KnowledgeDocumentStatusEnum.INDEX_FAILED
    assert "Embedding维度不匹配" in task.last_error


@pytest.mark.asyncio
async def test_process_delete_task_removes_chunks_without_calling_embedding(tmp_path):
    definition, task = build_execution_task(KnowledgeIndexTaskTypeEnum.DELETE)
    session = FakeExecutionSession()
    embedding_service = FakeEmbeddingService([])
    milvus_client = FakeMilvusClient()
    service = KnowledgeIndexService(
        session,
        knowledge_base_definition=definition,
        embedding_service=embedding_service,
        milvus_client=milvus_client,
        file_path_resolver=lambda storage_path: tmp_path / storage_path,
    )

    result = await service.process_task(task)

    assert result.succeeded is True
    assert result.chunk_count == 0
    assert task.document.status == KnowledgeDocumentStatusEnum.ARCHIVED
    assert embedding_service.received_texts == []
    assert milvus_client.delete_calls[0]["filter"] == 'document_id == "document-1"'


@pytest.mark.asyncio
async def test_embedding_service_embed_documents_sorts_response_by_input_index():
    class FakeEmbeddingsEndpoint:
        async def create(self, **kwargs):
            assert kwargs["input"] == ["first", "second"]
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[2.0]),
                    SimpleNamespace(index=0, embedding=[1.0]),
                ]
            )

    embedding_service = EmbeddingService(api_key="test-key")
    embedding_service.client = SimpleNamespace(embeddings=FakeEmbeddingsEndpoint())

    vectors = await embedding_service.embed_documents(["first", "second"])

    assert vectors == [[1.0], [2.0]]


@pytest.mark.asyncio
async def test_embedding_service_embed_documents_batches_by_configured_size():
    """超过供应商单次条数上限时，应按 batch_size 分批请求。"""

    class FakeEmbeddingsEndpoint:
        def __init__(self):
            self.calls: list[list[str]] = []

        async def create(self, **kwargs):
            batch = kwargs["input"]
            self.calls.append(batch)
            assert len(batch) <= 10
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=index, embedding=[float(index)])
                    for index in range(len(batch))
                ]
            )

    endpoint = FakeEmbeddingsEndpoint()
    embedding_service = EmbeddingService(api_key="test-key", batch_size=10)
    embedding_service.client = SimpleNamespace(embeddings=endpoint)

    texts = [f"chunk-{index}" for index in range(25)]
    vectors = await embedding_service.embed_documents(texts)

    assert [call_len for call_len in map(len, endpoint.calls)] == [10, 10, 5]
    assert len(vectors) == 25
    assert vectors[0] == [0.0]
    assert vectors[10] == [0.0]
    assert vectors[24] == [4.0]
