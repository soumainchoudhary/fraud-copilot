"""Health check and orchestration readiness endpoints."""
from pathlib import Path

from fastapi import APIRouter, Response, status

from app.config import get_settings
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns 200 OK if the service is running."""
    return HealthResponse(status="ok")


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    """Readiness probe — verifies core subsystem availability (DB, ML model)."""
    settings = get_settings()
    checks: dict[str, str] = {
        "status": "ready",
        "database": "unknown",
        "model": "unknown",
    }
    is_ready = True

    # Check database connectivity
    try:
        from sqlalchemy import text

        from app.db.database import get_engine
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"unhealthy: {e}"
        is_ready = False

    # Check ML model artifact
    model_path = Path(settings.model_path)
    if model_path.exists():
        checks["model"] = "available"
    else:
        checks["model"] = "missing_artifact"

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["status"] = "degraded"

    return checks

