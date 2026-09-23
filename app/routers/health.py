"""Health check endpoint."""
from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check — returns 200 OK if the service is running."""
    return HealthResponse(status="ok")
