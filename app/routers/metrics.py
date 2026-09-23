"""Prometheus metrics endpoint for cloud monitoring and alerting."""
from fastapi import APIRouter, Response

from app.metrics import metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=True)
def get_metrics() -> Response:
    """Export Prometheus-formatted performance and security telemetry."""
    return Response(
        content=metrics.export_text(),
        media_type="text/plain; version=0.0.4",
    )
