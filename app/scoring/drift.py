"""Concept drift monitoring using Population Stability Index (PSI) and feature distributions."""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


def calculate_psi(
    expected: Sequence[float],
    actual: Sequence[float],
    num_bins: int = 10,
    epsilon: float = 1e-4,
) -> float:
    """Calculate the Population Stability Index (PSI) between expected and actual distributions.

    PSI Formula:
        PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))

    Interpretations:
        PSI < 0.10: Stable (no significant distribution shift)
        0.10 <= PSI < 0.25: Moderate shift (warning)
        PSI >= 0.25: Significant drift (action/retraining required)
    """
    if len(expected) == 0 or len(actual) == 0:
        return 0.0

    exp_arr = np.array(expected, dtype=np.float64)
    act_arr = np.array(actual, dtype=np.float64)

    # Clean NaNs or infinities
    exp_arr = exp_arr[np.isfinite(exp_arr)]
    act_arr = act_arr[np.isfinite(act_arr)]

    if len(exp_arr) == 0 or len(act_arr) == 0:
        return 0.0

    # Determine quantile bin edges based on expected reference distribution
    percentiles = np.linspace(0, 100, num_bins + 1)
    bin_edges = np.percentile(exp_arr, percentiles)
    # Ensure strictly increasing bins
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) < 2:
        return 0.0

    # Extend outer boundaries
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    # Calculate bin counts
    exp_counts, _ = np.histogram(exp_arr, bins=bin_edges)
    act_counts, _ = np.histogram(act_arr, bins=bin_edges)

    # Convert to fractions with Laplace smoothing epsilon
    exp_pct = (exp_counts + epsilon) / (np.sum(exp_counts) + epsilon * len(exp_counts))
    act_pct = (act_counts + epsilon) / (np.sum(act_counts) + epsilon * len(act_counts))

    # Calculate PSI sum
    psi_value = np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct))
    return float(max(0.0, psi_value))


class DriftMonitor:
    """Thread-safe rolling drift detector tracking production inference streams against baselines."""

    def __init__(self, window_size: int = 500):
        self.window_size = window_size
        self.lock = threading.Lock()
        self.baseline_features: dict[str, list[float]] = {}
        self.inference_windows: dict[str, deque] = {}
        self._init_synthetic_baseline()

    def _init_synthetic_baseline(self) -> None:
        """Initialize reference distribution for Amount, Time, and key PCA features."""
        np.random.seed(42)
        n = 1000
        # Reference distributions matching typical non-fraud baseline
        self.baseline_features = {
            "amount": list(np.random.exponential(scale=88.0, size=n)),
            "v1": list(np.random.normal(loc=0.0, scale=1.9, size=n)),
            "v2": list(np.random.normal(loc=0.0, scale=1.6, size=n)),
            "v3": list(np.random.normal(loc=0.0, scale=1.5, size=n)),
            "v4": list(np.random.normal(loc=0.0, scale=1.4, size=n)),
            "v10": list(np.random.normal(loc=0.0, scale=1.1, size=n)),
            "v12": list(np.random.normal(loc=0.0, scale=1.0, size=n)),
            "v14": list(np.random.normal(loc=0.0, scale=0.9, size=n)),
            "v17": list(np.random.normal(loc=0.0, scale=0.8, size=n)),
        }
        for k in self.baseline_features:
            self.inference_windows[k] = deque(maxlen=self.window_size)

    def record_inference(self, feature_dict: dict[str, float]) -> None:
        """Record live inference features into rolling buffer."""
        with self.lock:
            for k, val in feature_dict.items():
                k_lower = k.lower()
                if k_lower in self.inference_windows and isinstance(val, (int, float)):
                    self.inference_windows[k_lower].append(float(val))

    def evaluate_drift(self) -> dict[str, Any]:
        """Compute current PSI and distribution shift status across monitored features."""
        with self.lock:
            feature_reports = {}
            max_psi = 0.0
            total_observations = 0

            for feature_name, expected_vals in self.baseline_features.items():
                window = list(self.inference_windows[feature_name])
                total_observations = max(total_observations, len(window))

                if len(window) < 10:
                    feature_reports[feature_name] = {
                        "psi": 0.0,
                        "status": "INSUFFICIENT_DATA",
                        "sample_size": len(window),
                    }
                    continue

                psi = calculate_psi(expected_vals, window, num_bins=10)
                psi_rounded = round(psi, 4)
                if psi_rounded > max_psi:
                    max_psi = psi_rounded

                if psi_rounded < 0.10:
                    status = "STABLE"
                elif psi_rounded < 0.25:
                    status = "MODERATE_DRIFT"
                else:
                    status = "CRITICAL_DRIFT"

                feature_reports[feature_name] = {
                    "psi": psi_rounded,
                    "status": status,
                    "sample_size": len(window),
                    "mean_actual": round(float(np.mean(window)), 4),
                    "mean_expected": round(float(np.mean(expected_vals)), 4),
                }

            if max_psi < 0.10:
                overall_status = "HEALTHY"
            elif max_psi < 0.25:
                overall_status = "WARNING_MODERATE_DRIFT"
            else:
                overall_status = "CRITICAL_MODEL_DRIFT"

            return {
                "overall_status": overall_status,
                "max_psi": max_psi,
                "window_capacity": self.window_size,
                "current_window_size": total_observations,
                "features": feature_reports,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }


# Singleton monitor
drift_monitor = DriftMonitor()
