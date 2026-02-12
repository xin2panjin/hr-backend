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

    bot, scheduler = await start_email_polling()

    yield
    # 2. yield之后的代码，是程序即将退出之前执行的
    await redis_client.close()
    if bot.is_connected():
        await bot.close()
    if scheduler.running:
        await scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router)
app.include_router(position_router)
app.include_router(candidate_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}
