"""Champion / Challenger shadow scoring pipeline for safe production model evaluation."""
from __future__ import annotations

import concurrent.futures
import threading
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from app.models.schemas import ScoreRequest, ScoreResponse

logger = structlog.get_logger(__name__)


class ChallengerModel:
    """Alternative challenger fraud scoring model emphasizing extreme sensitivity to velocity anomalies."""

    def __init__(self, threshold: float = 0.45):
        self.threshold = threshold
        self.version = "challenger-heuristic-v2"

    def predict_proba(self, request: ScoreRequest) -> float:
        """Calibrated non-linear risk scorer weighting primary fraud vectors (V14, V10, V4, V12, V17)."""
        # Primary fraud ring signal weights
        z = (
            -0.85 * request.v14
            - 0.55 * request.v10
            - 0.45 * request.v12
            - 0.35 * request.v17
            + 0.40 * request.v4
            + 0.00005 * min(request.amount, 50000.0)
            - 1.5  # base log-odds
        )
        # Sigmoid activation
        prob = 1.0 / (1.0 + np.exp(-np.clip(z, -15.0, 15.0)))
        return float(prob)


class ShadowScoringEngine:
    """Orchestrates shadow scoring in a background thread without impeding primary pipeline latency."""

    def __init__(self):
        self.challenger = ChallengerModel()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="shadow_scorer")
        self.lock = threading.Lock()
        self.total_evaluations: int = 0
        self.divergence_sum: float = 0.0
        self.agreement_count: int = 0
        self.champion_flagged: int = 0
        self.challenger_flagged: int = 0
        self.challenger_latencies: list[float] = []

    def score_challenger_async(self, request: ScoreRequest, champion_response: ScoreResponse) -> None:
        """Submit challenger evaluation asynchronously."""
        try:
            self.executor.submit(self._evaluate_shadow, request, champion_response)
        except Exception as e:
            logger.debug("shadow_scoring_submission_failed", error=str(e))

    def _evaluate_shadow(self, request: ScoreRequest, champion_resp: ScoreResponse) -> None:
        """Execute challenger model inference and record comparison telemetry."""
        t0 = time.perf_counter()
        challenger_score = self.challenger.predict_proba(request)
        latency_ms = (time.perf_counter() - t0) * 1000

        challenger_flagged = challenger_score >= self.challenger.threshold
        champion_flagged = champion_resp.flagged
        score_diff = abs(champion_resp.risk_score - challenger_score)
        agreement = (challenger_flagged == champion_flagged)

        with self.lock:
            self.total_evaluations += 1
            self.divergence_sum += score_diff
            if agreement:
                self.agreement_count += 1
            if champion_flagged:
                self.champion_flagged += 1
            if challenger_flagged:
                self.challenger_flagged += 1
            if len(self.challenger_latencies) < 1000:
                self.challenger_latencies.append(latency_ms)

        logger.debug(
            "shadow_evaluation_logged",
            txn_id=request.transaction_id,
            champ_score=champion_resp.risk_score,
            chall_score=round(challenger_score, 4),
            diff=round(score_diff, 4),
            agreement=agreement,
        )

    def get_metrics(self) -> dict[str, Any]:
        """Retrieve aggregated Champion vs Challenger comparison metrics."""
        with self.lock:
            n = self.total_evaluations
            mae = (self.divergence_sum / n) if n > 0 else 0.0
            agreement_rate = (self.agreement_count / n) if n > 0 else 1.0
            avg_latency = float(np.mean(self.challenger_latencies)) if self.challenger_latencies else 0.0

            return {
                "total_shadow_evaluations": n,
                "mean_absolute_error": round(mae, 4),
                "decision_agreement_rate": round(agreement_rate, 4),
                "champion_flagged_count": self.champion_flagged,
                "challenger_flagged_count": self.challenger_flagged,
                "average_challenger_latency_ms": round(avg_latency, 2),
                "challenger_model_version": self.challenger.version,
                "challenger_threshold": self.challenger.threshold,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }


# Singleton engine
shadow_engine = ShadowScoringEngine()
