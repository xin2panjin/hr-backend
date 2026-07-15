from fastapi import FastAPI
from routers.user_router import router as user_router
from routers.position_router import router as position_router
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from redis import asyncio as aioredis
from settings import settings
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache import FastAPICache
from routers.candidate_router import router as candidate_router
from scheduler import start_email_polling
from routers.dashboard_router import router as dashboard_router
from routers.media_router import router as media_router
from routers.talent_search_router import router as talent_search_router
from routers.assistant_router import router as assistant_router
from routers.iam_router import router as iam_router
from routers.knowledge_router import router as knowledge_router
from routers.candidate_portal_router import router as candidate_portal_router
from routers.candidate_communication_router import router as candidate_communication_router
from scheduler.candidate_communication import start_candidate_communication_scheduler

from loguru import logger

logger.remove()

logger.add(
    "log/app.log",
    rotation="10 MB",        # 每个文件最大 10MB
    retention="7 days",      # 保留最近 7 天的日志
    compression="zip",       # 压缩旧日志为 zip 文件
    level="INFO",            # 最低记录级别
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    encoding="utf-8",
    enqueue=True,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1. yield之前的代码，是程序运行前执行的
    redis_client = aioredis.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}",
        encoding="utf-8",
        decode_responses=True,
    )
    cache_backend = RedisBackend(redis_client)
    FastAPICache.init(cache_backend, prefix="fastapi-cache")

    bot = email_scheduler = None
    candidate_insight_scheduler = await start_candidate_communication_scheduler()
    if settings.ENABLE_EMAIL_POLLING:
        bot, email_scheduler = await start_email_polling()

    yield
    # 2. yield之后的代码，是程序即将退出之前执行的
    await redis_client.close()
    if bot and bot.is_connected:
        await bot.close()
    if email_scheduler and email_scheduler.running:
        await email_scheduler.shutdown()
    if candidate_insight_scheduler.running:
        await candidate_insight_scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router)
app.include_router(iam_router)
app.include_router(position_router)
app.include_router(candidate_router)
app.include_router(candidate_portal_router)
app.include_router(candidate_communication_router)
app.include_router(dashboard_router)
if settings.DEBUG:
    from routers.dev_router import router as dev_router

    app.include_router(media_router)
    app.include_router(dev_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}

app.include_router(talent_search_router)

app.include_router(assistant_router)
app.include_router(knowledge_router)
