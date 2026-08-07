from fastapi import APIRouter

from app.ai.registry import registry
from app.config.settings import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "version": settings.VERSION,
    }


@router.get("/agents")
async def agents():
    return registry.list()
