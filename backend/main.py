from fastapi import FastAPI
from app.config import settings
from app.api import router
from app.ai.bootstrap.bootstrap import bootstrap

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION
)

bootstrap()

app.include_router(router)

@app.get("/")
async def root():
    return {
        "application": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "running",
        "message": "Welcome to ContaMind AI 🚀"
    }