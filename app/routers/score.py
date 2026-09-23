"""Fraud scoring endpoint with real-time drift tracking, shadow scoring, and WebSocket broadcast."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter

from app.metrics import metrics
from app.models.schemas import BatchScoreRequest, BatchScoreResponse, ScoreRequest, ScoreResponse
from app.routers.stream import stream_manager
from app.scoring.drift import drift_monitor
from app.scoring.predict import score_batch, score_transaction
from app.scoring.shadow import shadow_engine

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["scoring"])


def _extract_feature_dict(req: ScoreRequest) -> dict[str, float]:
    """Extract numeric features from ScoreRequest for MLOps drift monitoring."""
    d = {"amount": float(req.amount), "time": float(req.time)}
    for i in range(1, 29):
        val = getattr(req, f"v{i}", None)
        if val is not None:
            d[f"v{i}"] = float(val)
    return d


@router.post("/score", response_model=ScoreResponse)
async def score(request: ScoreRequest) -> ScoreResponse:
    """Score a single transaction for fraud risk with MLOps drift and shadow scoring.

    Returns a risk score between 0.0 and 1.0, a boolean flag,
    model version, and Explainable AI risk factor attributions.
    """
    request_id = str(uuid.uuid4())
    logger.info("score_request", request_id=request_id, transaction_id=request.transaction_id)

    response = score_transaction(request)
    metrics.inc_scored(flagged=response.flagged)

    # 1. Record features for MLOps Concept Drift
    features = _extract_feature_dict(request)
    drift_monitor.record_inference(features)

    # 2. Asynchronous Champion / Challenger Shadow Scoring
    shadow_engine.score_challenger_async(request, response)

    # 3. Real-time WebSocket Broadcast
    if stream_manager.active_connections:
        asyncio.create_task(
            stream_manager.broadcast({
                "event": "TRANSACTION_SCORED",
                "transaction_id": response.transaction_id,
                "amount": request.amount,
                "risk_score": response.risk_score,
                "flagged": response.flagged,
                "alert_level": "CRITICAL" if response.risk_score >= 0.8 else ("WARNING" if response.flagged else "NORMAL"),
                "model_version": response.model_version,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        )

    logger.info(
        "score_response",
        request_id=request_id,
        transaction_id=response.transaction_id,
        risk_score=response.risk_score,
        flagged=response.flagged,
    )
    return response


@router.post("/score/batch", response_model=BatchScoreResponse)
async def score_transactions_batch(request: BatchScoreRequest) -> BatchScoreResponse:
    """Score a batch of transactions using vectorized inference.

    Accepts up to 100 transactions per request, scores them simultaneously,
    and returns individual risk assessments alongside aggregate batch metrics.
    """
    request_id = str(uuid.uuid4())
    logger.info("score_batch_request", request_id=request_id, batch_size=len(request.transactions))

    response = score_batch(request.transactions)
    for res in response.results:
        metrics.inc_scored(flagged=res.flagged, latency_seconds=response.total_latency_ms / (1000.0 * max(1, len(response.results))))

    # Record first transaction features for drift monitor and shadow scoring
    if request.transactions:
        drift_monitor.record_inference(_extract_feature_dict(request.transactions[0]))
        if response.results:
            shadow_engine.score_challenger_async(request.transactions[0], response.results[0])

    logger.info(
        "score_batch_response",
        request_id=request_id,
        total_processed=response.total_processed,
        total_flagged=response.total_flagged,
        latency_ms=response.total_latency_ms,
    )
    return response


@router.get("/scoring/drift")
def get_scoring_drift_report():
    """Retrieve real-time Population Stability Index (PSI) drift monitoring metrics."""
    return drift_monitor.evaluate_drift()


@router.get("/scoring/shadow-metrics")
def get_shadow_scoring_metrics():
    """Retrieve Champion vs Challenger model divergence and agreement telemetry."""
    return shadow_engine.get_metrics()
