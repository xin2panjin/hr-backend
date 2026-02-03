from fastapi import FastAPI
from routers.user_router import router as user_router
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}
