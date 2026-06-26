from fastapi import APIRouter
from fastapi.responses import FileResponse
import os
from settings import settings


router = APIRouter(prefix="/media", tags=['静态文件'])


@router.get("/{file_path}")
async def get_media_file(file_path: str):
    return FileResponse(os.path.join(settings.RESUME_DIR, file_path))