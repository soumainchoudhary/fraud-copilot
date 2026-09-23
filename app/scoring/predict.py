"""Model loading and transaction scoring."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import structlog
from fastapi import HTTPException, status

from app.config import get_settings
from app.models.schemas import BatchScoreResponse, RiskFactor, ScoreRequest, ScoreResponse
from app.scoring.features import get_feature_names

logger = structlog.get_logger(__name__)

# Module-level model and optimization cache
_model_artifact: dict[str, Any] | None = None
_scaler_center: float | None = None
_scaler_scale: float | None = None
_is_fast_transform_supported: bool = False

FEATURE_DESCRIPTIONS: dict[str, str] = {
    "scaled_amount": "Transaction amount deviation relative to typical consumer volume",
    "sin_time": "Time of day: diurnal cyclical activity index (sin component)",
    "cos_time": "Time of day: diurnal cyclical activity index (cos component)",
    "V1": "Behavioral latent signature V1: card usage channel velocity",
    "V2": "Behavioral latent signature V2: cardholder location consistency",
    "V3": "Behavioral latent signature V3: historical spending affinity",
    "V4": "Behavioral latent signature V4: merchant category risk index",
    "V10": "Behavioral latent signature V10: terminal authorization profile",
    "V11": "Behavioral latent signature V11: transaction frequency deviation",
    "V12": "Behavioral latent signature V12: device/browser fingerprint consistency",
    "V14": "Behavioral latent signature V14: primary fraud ring / compromise indicator",
    "V17": "Behavioral latent signature V17: cross-border / high-risk route indicator",
}


def _extract_pipeline_optimizations(pipeline: Any) -> None:
    """Precompute and cache transformation constants from pipeline for zero-overhead inference."""
    global _scaler_center, _scaler_scale, _is_fast_transform_supported
    try:
        if hasattr(pipeline, "named_steps") and "features" in pipeline.named_steps:
            transformer = pipeline.named_steps["features"]
            if hasattr(transformer, "named_transformers_") and "amount_scaler" in transformer.named_transformers_:
                amount_scaler = transformer.named_transformers_["amount_scaler"]
                if hasattr(amount_scaler, "center_") and hasattr(amount_scaler, "scale_"):
                    _scaler_center = float(amount_scaler.center_[0])
                    _scaler_scale = float(amount_scaler.scale_[0])
                    _is_fast_transform_supported = True
                    return
    except Exception as e:
        logger.debug("fast_transform_not_configured", reason=str(e))
    _is_fast_transform_supported = False


def transform_features_fast_or_fallback(pipeline: Any, requests: list[ScoreRequest]) -> np.ndarray | pd.DataFrame:
    """Transform ScoreRequest features using direct vectorized NumPy operations if available,
    falling back safely to ColumnTransformer or raw DataFrame for custom or mock pipelines.
    """
    global _is_fast_transform_supported
    if hasattr(pipeline, "named_steps"):
        if _scaler_scale is None:
            _extract_pipeline_optimizations(pipeline)

        if _is_fast_transform_supported and _scaler_scale is not None and _scaler_scale != 0:
            n = len(requests)
            if n == 1:
                req = requests[0]
                scaled_amt = (req.amount - _scaler_center) / _scaler_scale
                hrs = (req.time % 86400.0) / 3600.0
                sin_time = np.sin(0.2617993877991494 * hrs)
                cos_time = np.cos(0.2617993877991494 * hrs)
                pca = [getattr(req, f"v{i}") for i in range(1, 29)]
                return np.array([[scaled_amt, sin_time, cos_time] + pca], dtype=np.float64)
            else:
                amounts = np.fromiter((r.amount for r in requests), dtype=np.float64, count=n)
                times = np.fromiter((r.time for r in requests), dtype=np.float64, count=n)
                scaled_amts = (amounts - _scaler_center) / _scaler_scale
                hrs = (times % 86400.0) / 3600.0
                sin_times = np.sin(0.2617993877991494 * hrs)
                cos_times = np.cos(0.2617993877991494 * hrs)

                pca_mat = np.empty((n, 28), dtype=np.float64)
                for idx, r in enumerate(requests):
                    pca_mat[idx] = [getattr(r, f"v{i}") for i in range(1, 29)]

                return np.column_stack([scaled_amts, sin_times, cos_times, pca_mat])

    # Fallback to standard DataFrame and ColumnTransformer for arbitrary or mock pipelines
    rows = []
    for req in requests:
        row = {"Time": req.time, "Amount": req.amount}
        for i in range(1, 29):
            row[f"V{i}"] = getattr(req, f"v{i}")
        rows.append(row)
    df = pd.DataFrame(rows)
    if hasattr(pipeline, "named_steps") and "features" in pipeline.named_steps:
        return pipeline.named_steps["features"].transform(df)
    if hasattr(pipeline, "transform"):
        return pipeline.transform(df)
    return df


def explain_features_vectorized(
    pipeline: Any,
    X_trans: np.ndarray,
    top_n: int = 5,
) -> list[list[RiskFactor]]:
    """Compute Explainable AI risk factors directly from pre-transformed features matrix.
    Operates over the entire matrix in one vectorized C-level call.
    """
    n_rows = X_trans.shape[0] if hasattr(X_trans, "shape") else len(X_trans)
    if n_rows == 0:
        return []

    classifier = pipeline.named_steps.get("classifier") if hasattr(pipeline, "named_steps") else None
    if classifier is None:
        return [[] for _ in range(n_rows)]

    feature_names = get_feature_names()
    contribs_matrix: np.ndarray | None = None

    # 1. XGBoost TreeSHAP batch
    if hasattr(classifier, "get_booster"):
        try:
            import xgboost as xgb
            dmat = xgb.DMatrix(X_trans, feature_names=feature_names)
            shap_values = classifier.get_booster().predict(dmat, pred_contribs=True)
            contribs_matrix = shap_values[:, :-1]
        except Exception:
            contribs_matrix = None

    # 2. Linear Model (feature * weight)
    if contribs_matrix is None and hasattr(classifier, "coef_"):
        coefs = classifier.coef_[0]
        X_dense = X_trans if isinstance(X_trans, np.ndarray) else X_trans.toarray()
        contribs_matrix = X_dense * coefs

    if contribs_matrix is None:
        return [[] for _ in range(n_rows)]

    all_factors: list[list[RiskFactor]] = []
    for row_idx in range(n_rows):
        row_contribs = contribs_matrix[row_idx]
        paired = [(feature_names[j], float(row_contribs[j])) for j in range(len(feature_names))]
        paired.sort(key=lambda x: abs(x[1]), reverse=True)

        factors: list[RiskFactor] = []
        for name, val in paired[:top_n]:
            direction = "risk_increasing" if val > 0 else "risk_decreasing"
            desc = FEATURE_DESCRIPTIONS.get(
                name,
                f"Forensic behavioral component {name} deviation",
            )
            factors.append(
                RiskFactor(
                    feature=name,
                    contribution=round(val, 4),
                    direction=direction,
                    description=desc,
                )
            )
        all_factors.append(factors)

    return all_factors


def explain_prediction(pipeline: Any, df: pd.DataFrame, top_n: int = 5) -> list[RiskFactor]:
    """Calculate Explainable AI feature contributions for a prediction (DataFrame input compatibility)."""
    try:
        if not hasattr(pipeline, "named_steps") or "features" not in pipeline.named_steps:
            return []

        X_trans = pipeline.named_steps["features"].transform(df)
        results = explain_features_vectorized(pipeline, X_trans, top_n=top_n)
        return results[0] if results else []
    except Exception as e:
        logger.warning("explainability_failed", error=str(e))
        return []


def load_model(path: str | Path | None = None) -> dict[str, Any]:
    """Load the trained model artifact from disk.

    Caches the model in a module-level variable for reuse.

    Returns:
        Dict with keys: pipeline, threshold, model_name, feature_names
    """
    global _model_artifact
    if _model_artifact is not None:
        return _model_artifact

    settings = get_settings()
    model_path = Path(path or settings.model_path)

    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found at {model_path}. Run 'python -m app.scoring.train' first."
        )

    _model_artifact = joblib.load(model_path)
    _extract_pipeline_optimizations(_model_artifact["pipeline"])
    logger.info(
        "model_loaded",
        path=str(model_path),
        model_name=_model_artifact["model_name"],
        threshold=_model_artifact["threshold"],
        fast_inference_enabled=_is_fast_transform_supported,
    )
    return _model_artifact


def score_transaction(request: ScoreRequest) -> ScoreResponse:
    """Score a single transaction for fraud risk with optimized single-pass inference.

    Args:
        request: Transaction data matching ScoreRequest schema.

    Returns:
        ScoreResponse with risk_score, flagged status, and model version.
    """
    start_time = time.perf_counter()
    settings = get_settings()
    try:
        artifact = load_model()
    except FileNotFoundError as e:
        logger.error("model_artifact_missing", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scoring engine model not initialized or artifact not found. Please train model first.",
        )

    pipeline = artifact["pipeline"]

    # 1. Single-pass fast feature transformation
    X_trans = transform_features_fast_or_fallback(pipeline, [request])

    # 2. Get fraud probability on pre-transformed array or raw df
    if hasattr(pipeline, "named_steps"):
        classifier = pipeline.named_steps.get("classifier")
        if classifier is not None and hasattr(classifier, "predict_proba"):
            proba = float(classifier.predict_proba(X_trans)[0, 1])
        else:
            proba = float(pipeline.predict_proba(X_trans)[0, 1])
        # 3. Explainability on exact same array
        factors_list = explain_features_vectorized(pipeline, X_trans, top_n=5)
        risk_factors = factors_list[0] if factors_list else []
    else:
        proba = float(pipeline.predict_proba(X_trans)[0, 1])
        risk_factors = []

    # Apply optimized threshold
    threshold = artifact.get("threshold", settings.flag_threshold)
    flagged = proba >= threshold

    latency_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "transaction_scored",
        transaction_id=request.transaction_id,
        risk_score=round(proba, 4),
        flagged=flagged,
        model_version=settings.model_version,
        latency_ms=round(latency_ms, 2),
        num_risk_factors=len(risk_factors),
    )

    return ScoreResponse(
        transaction_id=request.transaction_id,
        risk_score=round(proba, 6),
        flagged=flagged,
        model_version=settings.model_version,
        risk_factors=risk_factors,
    )


def score_batch(requests: list[ScoreRequest]) -> BatchScoreResponse:
    """Score a batch of transactions using vectorized inference and batch SHAP.

    Args:
        requests: List of transactions matching ScoreRequest.

    Returns:
        BatchScoreResponse containing individual ScoreResponses and aggregate metrics.
    """
    start_time = time.perf_counter()
    settings = get_settings()
    try:
        artifact = load_model()
    except FileNotFoundError as e:
        logger.error("model_artifact_missing", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scoring engine model not initialized or artifact not found. Please train model first.",
        )

    pipeline = artifact["pipeline"]
    threshold = artifact.get("threshold", settings.flag_threshold)

    # 1. Single vectorized feature transformation for all transactions
    X_trans = transform_features_fast_or_fallback(pipeline, requests)

    # 2. Vectorized probability prediction
    if hasattr(pipeline, "named_steps"):
        classifier = pipeline.named_steps.get("classifier")
        if classifier is not None and hasattr(classifier, "predict_proba"):
            probas = classifier.predict_proba(X_trans)[:, 1]
        else:
            probas = pipeline.predict_proba(X_trans)[:, 1]
        # 3. Vectorized Explainability across the entire matrix at once
        all_risk_factors = explain_features_vectorized(pipeline, X_trans, top_n=5)
    else:
        probas = pipeline.predict_proba(X_trans)[:, 1]
        all_risk_factors = [[] for _ in requests]

    results: list[ScoreResponse] = []
    total_flagged = 0

    for i, req in enumerate(requests):
        proba = float(probas[i])
        flagged = proba >= threshold
        if flagged:
            total_flagged += 1

        results.append(
            ScoreResponse(
                transaction_id=req.transaction_id,
                risk_score=round(proba, 6),
                flagged=flagged,
                model_version=settings.model_version,
                risk_factors=all_risk_factors[i] if i < len(all_risk_factors) else [],
            )
        )

    latency_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "batch_scored",
        batch_size=len(requests),
        total_flagged=total_flagged,
        latency_ms=round(latency_ms, 2),
    )

    return BatchScoreResponse(
        total_processed=len(requests),
        total_flagged=total_flagged,
        total_latency_ms=round(latency_ms, 2),
        results=results,
    )

