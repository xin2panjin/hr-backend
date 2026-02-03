import asyncio
from repository.user_repo import UserRepo, DepartmentRepo
from models import AsyncSessionFactory
import sys
# Fix for Windows psycopg issue with ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def init_department():
    async with AsyncSessionFactory() as session:
        # 开启事务
        async with session.begin():
            department_repo = DepartmentRepo(session)
            department_dict_list = [
                {"name": "人事部", "description": "人事部门"},
                {"name": "技术部", "description": "负责产品和技术部"},
                {"name": "运营部", "description": "负责产品和用户运营"},
                {"name": "市场部", "description": "负责市场推广和品牌建设"},
                {"name": "财务部", "description": "负责财务管理和审计"},
                {"name": "法务部", "description": "负责法律事务和合规管理"},
                {"name": "行政部", "description": "负责行政管理和后勤保障"},
                {"name": "客服部", "description": "负责客户服务和投诉处理"}
            ]
            for department_dict in department_dict_list:
                await department_repo.create_department(department_dict)
        print("部门初始化完成！")

async def init_user():
    async with AsyncSessionFactory() as session:
        async with session.begin():
            user_repo = UserRepo(session)
            department_repo = DepartmentRepo(session)
            hr_department = await department_repo.get_by_name("人事部")
            tech_department = await department_repo.get_by_name("技术部")
            operator_department = await department_repo.get_by_name("运营部")
            market_department = await department_repo.get_by_name("市场部")
            finance_department = await department_repo.get_by_name("财务部")
            legal_department = await department_repo.get_by_name("法务部")
            admin_department = await department_repo.get_by_name("行政部")
            customer_service_department = await department_repo.get_by_name("客服部")
            users_dict_list = [
                {
                    "username": "Boss",
                    "password": "111111",
                    "email": "boss@qq.com",
                    "realname": "黄老板",
                    "is_superuser": True,
                    "department_id": hr_department.id,
                }, {
                    "username": "hr",
                    "password": "111111",
                    "email": "hr@qq.com",
                    "realname": "周HR",
                    "is_superuser": False,
                    "department_id": hr_department.id,
                }, {
                    "username": "tech",
                    "password": "111111",
                    "email": "tech@qq.com",
                    "realname": "张技术",
                    "is_superuser": False,
                    "department_id": tech_department.id,
                }, {
                    "username": "operator",
                    "password": "111111",
                    "email": "operator@qq.com",
                    "realname": "孙运营",
                    "is_superuser": False,
                    "department_id": operator_department.id,
                }, {
                    "username": "market",
                    "password": "111111",
                    "email": "market@qq.com",
                    "realname": "李市场",
                    "is_superuser": False,
                    "department_id": market_department.id,
                }, {
                    "username": "finance",
                    "password": "111111",
                    "email": "finance@qq.com",
                    "realname": "王财务",
                    "is_superuser": False,
                    "department_id": finance_department.id,
                }, {
                    "username": "legal",
                    "password": "111111",
                    "email": "legal@qq.com",
                    "realname": "赵法务",
                    "is_superuser": False,
                    "department_id": legal_department.id,
                }, {
                    "username": "admin",
                    "password": "111111",
                    "email": "admin@qq.com",
                    "realname": "王行政",
                    "is_superuser": False,
                    "department_id": admin_department.id,
                }, {
                    "username": "service",
                    "password": "111111",
                    "email": "service@qq.com",
                    "realname": "张客服",
                    "is_superuser": False,
                    "department_id": customer_service_department.id,
                }
            ]
            for user_dict in users_dict_list:
                await user_repo.create_user(user_dict)
        print("用户初始化完成！")

async def main():
    # 1. 先初始化部门
    await init_department()
    # 2. 初始化用户
    await init_user()

if __name__ == '__main__':
    asyncio.run(main())