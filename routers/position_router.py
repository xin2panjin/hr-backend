from datetime import datetime

from fastapi import Depends, APIRouter, HTTPException, Query
from models.user import UserModel
from dependencies import get_current_user, get_session_instance
from models import AsyncSession
from schemas.position_schema import PositionCreateSchema, PositionRespSchema, PositionListRespSchema
from repository.position_repo import PositionRepo
from schemas import ResponseSchema
from fastapi import status
from iam.policies.position_policy import PositionPolicy
from models.positions import EducationEnum

router = APIRouter(prefix="/position", tags=["position"])

@router.post("/create", summary="创建职位", response_model=PositionRespSchema)
async def create_position(
    position_data: PositionCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        position_repo = PositionRepo(session=session)
        position_dict = position_data.model_dump()
        position_dict['creator_id'] = current_user.id
        position_dict['department_id'] = current_user.department.id
        PositionPolicy.ensure_can_create(current_user, position_dict['department_id'])
        position = await position_repo.create_position(position_dict)
        return {"position": position}

@router.get('/list', summary="职位列表", response_model=PositionListRespSchema)
async def get_position_list(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=100),
    department_id: str | None = None,
    is_open: bool | None = None,
    education: EducationEnum | None = None,
    work_year_min: int | None = Query(default=None, ge=0),
    work_year_max: int | None = Query(default=None, ge=0),
    created_at_start: datetime | None = None,
    created_at_end: datetime | None = None,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    if work_year_min is not None and work_year_max is not None and work_year_min > work_year_max:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="最低年限不能大于最高年限")
    if created_at_start and created_at_end and created_at_start > created_at_end:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="创建时间起始不能晚于结束")
    async with session.begin():
        position_repo = PositionRepo(session=session)
        positions, total = await position_repo.get_possition_list(
            current_user,
            page=page,
            size=size,
            keyword=keyword,
            department_id=department_id,
            is_open=is_open,
            education=education,
            work_year_min=work_year_min,
            work_year_max=work_year_max,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
        )
        return {"positions": positions, "total": total, "page": page, "size": size}

@router.delete("/delete/{position_id}", summary="删除职位")
async def delete_position(
    position_id: str,
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        position_repo = PositionRepo(session=session)
        position = await position_repo.get_by_id(position_id)
        if not position:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该职位不存在！")
        PositionPolicy.ensure_can_delete(current_user, position)

        # 执行删除操作
        try:
            await position_repo.delete_position(position_id)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="职位删除失败！")
        return ResponseSchema()
