from fastapi import APIRouter

from app.ai.registry import registry

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "application": "ContaMind AI",
        "version": "1.0.0",
    }


@router.get("/agents")
async def agents():
    return registry.list()
