from fastapi import FastAPI
from . import models


app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}
