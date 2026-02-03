from models import AsyncSessionFactory, AsyncSession
from core.auth import AuthHandler


async def get_session_instance():
    session: AsyncSession = AsyncSessionFactory()
    try:
        yield session
    finally:
        await session.close()

async def get_auth_handler():
    return AuthHandler()