from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.bootstrap.bootstrap import bootstrap
from app.api.router import api_router
from app.config.settings import settings
from app.database import Base, engine
from app.models import user as user_models  # noqa: F401  (registra modelos para create_all)
from app.shared.errors import register_exception_handlers
from app.shared.logging import RequestLoggingMiddleware, configure_logging

configure_logging(debug=settings.DEBUG)
bootstrap()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    debug=settings.DEBUG,
)

register_exception_handlers(app)

if settings.DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)
app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["platform"])
async def root() -> dict[str, str]:
    return {
        "application": settings.APP_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "running",
    }


@app.get("/health", tags=["platform"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.APP_NAME}
