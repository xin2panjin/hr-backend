from fastapi import Depends, APIRouter, HTTPException
from models.user import UserModel
from dependencies import get_current_user, get_session_instance
from models import AsyncSession
from schemas.position_schema import PositionCreateSchema, PositionRespSchema, PositionListRespSchema
from repository.position_repo import PositionRepo
from schemas import ResponseSchema
from fastapi import status

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
        position = await position_repo.create_position(position_dict)
        return {"position": position}

@router.get('/list', summary="职位列表", response_model=PositionListRespSchema)
async def get_position_list(
    page: int = 1,
    size: int = 10,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        position_repo = PositionRepo(session=session)
        positions = await position_repo.get_possition_list(current_user, page=page, size=size)
        return {"positions": positions}

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
        # 如果是superuser，那么可以直接删除；否则就只能是所属部门的人才能删除
        if (not current_user.is_superuser) and (position.department_id != current_user.department.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限执行操作！")

        # 执行删除操作
        await position_repo.delete_position(position_id)
        return ResponseSchema()