"""企业制度知识库管理接口。"""

import json
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select

from dependencies import get_session_instance, require_permission
from iam.permissions import PermissionCode
from knowledge.recruiting_policy import RECRUITING_POLICY_KNOWLEDGE_BASE_KEY
from models import AsyncSession
from models.knowledge import KnowledgeDocumentStatusEnum, KnowledgeIndexTaskModel
from models.user import UserModel
from rag.retrieval_types import RetrievalMode
from schemas.knowledge_schema import (
    KnowledgeDocumentListSchema,
    KnowledgeDocumentPreviewSchema,
    KnowledgeDocumentSchema,
    KnowledgeIndexTaskListSchema,
    KnowledgeIndexTaskSchema,
    KnowledgeRetrievalConfigSchema,
    KnowledgeTextProcessingConfigSchema,
)
from services.knowledge_document_service import (
    KnowledgeDocumentService,
    KnowledgeDocumentValidationError,
)
from services.knowledge_search_service import KnowledgeSearchService
from services.knowledge_retrieval_config_service import (
    KnowledgeRetrievalConfigNotFoundError,
    KnowledgeRetrievalConfigService,
)
from services.knowledge_preview_service import KnowledgePreviewService
from services.knowledge_text_extractor import KnowledgeTextExtractionError
from services.knowledge_text_processing import KnowledgeTextProcessingConfig
from schemas.knowledge_search_schema import (
    KnowledgeSearchRequestSchema,
    KnowledgeSearchResponseSchema,
)
from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition
from tasks.knowledge_tasks import run_recruiting_policy_index_task


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _parse_processing_config(
    raw_value: str | None,
) -> KnowledgeTextProcessingConfig:
    """解析 multipart 表单中的 JSON 配置，并复用服务层范围校验。"""

    try:
        parsed_value = json.loads(raw_value) if raw_value else {}
        if not isinstance(parsed_value, dict):
            raise ValueError("文本处理配置必须为 JSON 对象")
        validated_value = KnowledgeTextProcessingConfigSchema.model_validate(parsed_value)
        return KnowledgeTextProcessingConfig.from_mapping(validated_value.model_dump())
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"文本处理配置无效：{error}") from error


@router.post("/search", response_model=KnowledgeSearchResponseSchema, summary="检索制度知识库")
async def search_knowledge(
    search_data: KnowledgeSearchRequestSchema,
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(require_permission(PermissionCode.ASSISTANT_USE)),
):
    """提供给 HR 助手 Tool 和内部调试使用的制度切片检索入口。"""

    try:
        async with session.begin():
            retrieval_config = await KnowledgeRetrievalConfigService(
                session=session
            ).get_config(knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY)
        result = await KnowledgeSearchService(
            knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(
                retrieval_config=retrieval_config.model_dump()
            ),
        ).search(
            query=search_data.query,
            top_k=search_data.top_k,
            retrieval_mode=search_data.retrieval_mode,
        )
    except KnowledgeRetrievalConfigNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "hits": [hit.to_dict() for hit in result.hits],
        "knowledge_base_key": result.knowledge_base_key,
        "retrieval_mode": result.retrieval_mode,
        "trace_id": result.trace_id,
        "elapsed_ms": result.elapsed_ms,
        "reranked": result.reranked,
        "rerank_elapsed_ms": result.rerank_elapsed_ms,
        "artifact": {
            "type": "knowledge_sources",
            "title": "制度知识来源",
            "knowledge_base_key": result.knowledge_base_key,
            "trace_id": result.trace_id,
            "sources": [source.to_dict() for source in result.sources],
        },
    }


@router.get(
    "/retrieval-config",
    response_model=KnowledgeRetrievalConfigSchema,
    summary="读取制度知识库检索策略",
)
async def get_retrieval_config(
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    try:
        async with session.begin():
            return await KnowledgeRetrievalConfigService(session=session).get_config(
                knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY
            )
    except KnowledgeRetrievalConfigNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put(
    "/retrieval-config",
    response_model=KnowledgeRetrievalConfigSchema,
    summary="更新制度知识库检索策略",
)
async def update_retrieval_config(
    config: KnowledgeRetrievalConfigSchema,
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    try:
        async with session.begin():
            return await KnowledgeRetrievalConfigService(session=session).update_config(
                knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
                config=config,
            )
    except KnowledgeRetrievalConfigNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _document_schema(document) -> KnowledgeDocumentSchema:
    return KnowledgeDocumentSchema(
        id=document.id, title=document.title, category=document.category,
        file_name=document.file_name, file_type=document.file_type, version=document.version,
        effective_date=document.effective_date,
        status=getattr(document.status, "value", document.status),
        visibility_scope=document.visibility_scope, indexed_at=document.indexed_at,
        created_at=document.created_at, updated_at=document.updated_at,
    )


def _task_schema(task) -> KnowledgeIndexTaskSchema:
    return KnowledgeIndexTaskSchema(
        id=task.id, document_id=task.document_id,
        task_type=getattr(task.task_type, "value", task.task_type),
        status=getattr(task.status, "value", task.status),
        target_chunk_version=task.target_chunk_version, retry_count=task.retry_count,
        last_error=task.last_error, created_at=task.created_at, completed_at=task.completed_at,
    )


@router.post("/documents", response_model=KnowledgeDocumentSchema, summary="上传并登记制度文档")
async def create_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str | None = Form(default=None),
    version: str | None = Form(default=None),
    effective_date: date | None = Form(default=None),
    processing_config: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    try:
        parsed_processing_config = _parse_processing_config(processing_config)
        async with session.begin():
            result = await KnowledgeDocumentService(session=session).register_document(
                knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
                source=file, title=title, category=category, version=version,
                effective_date=effective_date, created_by=current_user.id,
                processing_config=parsed_processing_config,
            )
    except (KnowledgeDocumentValidationError, KnowledgeTextExtractionError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    background_tasks.add_task(run_recruiting_policy_index_task, result.index_task.id)
    return _document_schema(result.document)


@router.post(
    "/documents/preview",
    response_model=KnowledgeDocumentPreviewSchema,
    summary="预览制度文档的清洗和切片结果",
)
async def preview_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    processing_config: str | None = Form(default=None),
    _: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    """返回纯计算预览，不创建文档、任务、向量或 Embedding 请求。"""

    try:
        parsed_processing_config = _parse_processing_config(processing_config)
        result = await KnowledgePreviewService().preview(
            source=file,
            document_title=title,
            processing_config=parsed_processing_config,
        )
    except (KnowledgeDocumentValidationError, KnowledgeTextExtractionError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "raw_block_count": result.raw_block_count,
        "cleaned_block_count": result.cleaned_block_count,
        "chunk_count": result.chunk_count,
        "total_characters": result.total_characters,
        "preview_truncated": result.preview_truncated,
        "processing_config": result.processing_config.to_dict(),
        "chunks": [
            {
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "character_count": len(chunk.content),
                "token_count": chunk.token_count,
                "section_path": chunk.section_path,
                "page_number": chunk.page_number,
            }
            for chunk in result.chunks
        ],
    }


@router.get("/documents", response_model=KnowledgeDocumentListSchema, summary="查询制度文档")
async def list_documents(
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    status: KnowledgeDocumentStatusEnum | None = Query(default=None),
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    async with session.begin():
        documents, total = await KnowledgeDocumentService(session=session).list_documents(
            knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
            page=page, size=size, document_status=status,
        )
    return {"items": [_document_schema(item) for item in documents], "total": total, "page": page, "size": size}


@router.post("/documents/{document_id}/reindex", response_model=KnowledgeIndexTaskSchema, summary="重建制度文档索引")
async def reindex_document(
    document_id: str, background_tasks: BackgroundTasks,
    processing_config: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    try:
        parsed_processing_config = (
            _parse_processing_config(processing_config)
            if processing_config is not None
            else None
        )
        async with session.begin():
            task = await KnowledgeDocumentService(session=session).request_rebuild(
                knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
                document_id=document_id, actor_id=current_user.id,
                processing_config=parsed_processing_config,
            )
    except KnowledgeDocumentValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    background_tasks.add_task(run_recruiting_policy_index_task, task.id)
    return _task_schema(task)


@router.delete("/documents/{document_id}", response_model=KnowledgeIndexTaskSchema, summary="归档制度文档并清理索引")
async def archive_document(
    document_id: str, background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    try:
        async with session.begin():
            task = await KnowledgeDocumentService(session=session).archive_document(
                knowledge_base_key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
                document_id=document_id, actor_id=current_user.id,
            )
    except KnowledgeDocumentValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    background_tasks.add_task(run_recruiting_policy_index_task, task.id)
    return _task_schema(task)


@router.get("/index-tasks", response_model=KnowledgeIndexTaskListSchema, summary="查看制度索引任务")
async def list_index_tasks(
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), document_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(require_permission(PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE)),
):
    async with session.begin():
        filters = [KnowledgeIndexTaskModel.knowledge_base.has(key=RECRUITING_POLICY_KNOWLEDGE_BASE_KEY)]
        if document_id:
            filters.append(KnowledgeIndexTaskModel.document_id == document_id)
        tasks = list(await session.scalars(select(KnowledgeIndexTaskModel).where(*filters).order_by(KnowledgeIndexTaskModel.created_at.desc()).offset((page - 1) * size).limit(size)))
        total = int(await session.scalar(select(func.count(KnowledgeIndexTaskModel.id)).where(*filters)) or 0)
    return {"items": [_task_schema(item) for item in tasks], "total": total, "page": page, "size": size}
