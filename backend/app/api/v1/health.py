from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():

    return {
        "status": "healthy",
        "application": "ContaMind AI",
        "version": "1.0.0"
    }