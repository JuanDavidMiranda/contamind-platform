from fastapi import FastAPI
from app.ai.registry import registry
from app.ai.agents.dian.agent import DianAgent
from app.api.router import api_router
from app.config.settings import settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION
)

# Registrar agentes
registry.register(DianAgent())

# Registrar rutas
app.include_router(api_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "application": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "running",
        "message": "Welcome to ContaMind AI 🚀"
    }