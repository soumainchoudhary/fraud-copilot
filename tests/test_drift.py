"""Tests for concept drift monitoring and Population Stability Index (PSI) calculations."""
import numpy as np

from app.scoring.drift import DriftMonitor, calculate_psi


class TestConceptDrift:

    def test_psi_identical_distributions_near_zero(self):
        np.random.seed(42)
        expected = np.random.normal(0, 1, 1000)
        actual = np.random.normal(0, 1, 1000)

        psi = calculate_psi(expected, actual, num_bins=10)
        # Should be very close to 0 (< 0.05)
        assert psi < 0.05

    def test_psi_shifted_distribution_triggers_drift(self):
        np.random.seed(42)
        expected = np.random.normal(0, 1, 1000)
        # Severe shift in mean and variance
        actual = np.random.normal(4.0, 3.0, 1000)

        psi = calculate_psi(expected, actual, num_bins=10)
        # Shifted distribution must exceed significant drift threshold (>= 0.25)
        assert psi >= 0.25

    def test_drift_monitor_evaluation_cycle(self):
        monitor = DriftMonitor(window_size=100)

        # Feed 30 inferences resembling baseline
        for _ in range(30):
            monitor.record_inference({
                "amount": float(np.random.exponential(scale=88.0)),
                "v14": float(np.random.normal(0, 0.9)),
                "v10": float(np.random.normal(0, 1.1)),
            })

        report = monitor.evaluate_drift()
        assert "overall_status" in report
        assert "max_psi" in report
        assert "features" in report
        assert "amount" in report["features"]
        assert report["features"]["amount"]["sample_size"] == 30
        assert report["overall_status"] in ("HEALTHY", "WARNING_MODERATE_DRIFT", "CRITICAL_MODEL_DRIFT")
