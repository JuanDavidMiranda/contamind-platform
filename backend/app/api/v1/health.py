import logging

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.ai.registry import registry
from app.config.settings import settings
from app.database import engine
from app.shared.errors import app_error

logger = logging.getLogger("contamind.health")

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "version": settings.VERSION,
    }


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.error(
            "readiness check failed",
            exc_info=True,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        raise app_error(
            "SERVICE_UNAVAILABLE",
            message="La base de datos no está disponible.",
        )
    return {"status": "ready", "database": "up"}


@router.get("/agents")
async def agents():
    return registry.list()
