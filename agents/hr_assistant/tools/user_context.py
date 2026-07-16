"""HR 助手 Tool 使用的用户权限上下文加载。"""

from repository.iam_repo import IamRepo
from repository.user_repo import UserRepo


async def load_user_with_active_roles(session, user_id: str):
    """重新加载用户及其有效角色，供候选人数据范围策略使用。

    Tool 在独立数据库会话中运行，不能复用 HTTP 依赖层临时挂载的
    ``iam_roles``。候选人检索、详情和对比都依赖该字段解析数据范围，
    因此必须在这里重新加载。
    """

    user = await UserRepo(session).get_by_id(user_id)
    if not user:
        return None

    user.iam_roles = await IamRepo(session).get_active_user_roles(user.id)
    return user
