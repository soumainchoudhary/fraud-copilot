"""Tests for the fraud scoring engine."""
import numpy as np
import pandas as pd
import pytest

from app.models.schemas import ScoreRequest, ScoreResponse
from app.scoring.features import (
    build_feature_transformer,
    get_feature_names,
    prepare_dataframe,
)


class TestFeaturePreparation:
    """Tests for feature engineering pipeline."""

    def test_build_transformer_returns_column_transformer(self):
        transformer = build_feature_transformer()
        assert hasattr(transformer, "fit")
        assert hasattr(transformer, "transform")

    def test_transform_output_shape(self, sample_dataset):
        transformer = build_feature_transformer()
        X = sample_dataset.drop(columns=["Class"])
        transformed = transformer.fit_transform(X)
        # 1 (Amount) + 2 (sin_time, cos_time) + 28 (V1-V28) = 31
        assert transformed.shape[1] == 31
        assert transformed.shape[0] == len(X)

    def test_amount_scaling_robust(self, sample_dataset):
        """Verify Amount is scaled using RobustScaler."""
        transformer = build_feature_transformer()
        X = sample_dataset.drop(columns=["Class"])
        transformed = transformer.fit_transform(X)
        # First column is scaled amount — should have median ~0
        scaled_amount = transformed[:, 0]
        assert abs(np.median(scaled_amount)) < 0.01

    def test_time_cyclic_encoding(self, sample_dataset):
        """Verify Time is encoded as sin/cos (bounded [-1, 1])."""
        transformer = build_feature_transformer()
        X = sample_dataset.drop(columns=["Class"])
        transformed = transformer.fit_transform(X)
        sin_time = transformed[:, 1]
        cos_time = transformed[:, 2]
        assert np.all(sin_time >= -1.0) and np.all(sin_time <= 1.0)
        assert np.all(cos_time >= -1.0) and np.all(cos_time <= 1.0)

    def test_pca_features_unchanged(self, sample_dataset):
        """Verify V1-V28 pass through without modification."""
        transformer = build_feature_transformer()
        X = sample_dataset.drop(columns=["Class"])
        transformed = transformer.fit_transform(X)
        # PCA features start at index 3
        for i in range(28):
            col_name = f"V{i+1}"
            np.testing.assert_array_almost_equal(
                transformed[:, 3 + i],
                X[col_name].values,
            )

    def test_get_feature_names(self):
        names = get_feature_names()
        assert len(names) == 31
        assert names[0] == "scaled_amount"
        assert names[1] == "sin_time"
        assert names[2] == "cos_time"
        assert names[3] == "V1"
        assert names[-1] == "V28"


class TestDataPreparation:
    """Tests for data cleaning."""

    def test_deduplication(self, sample_dataset):
        # Add duplicates
        df_with_dupes = pd.concat([sample_dataset, sample_dataset.iloc[:5]], ignore_index=True)
        cleaned = prepare_dataframe(df_with_dupes)
        assert len(cleaned) == len(sample_dataset)

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"A": [1], "B": [2]})
        with pytest.raises(ValueError, match="Missing expected columns"):
            prepare_dataframe(df)

    def test_valid_dataset_passes(self, sample_dataset):
        cleaned = prepare_dataframe(sample_dataset)
        assert len(cleaned) == len(sample_dataset)


class TestModelScoring:
    """Tests for the prediction logic."""

    def test_score_returns_bounded_risk(self, mock_model_artifact):
        """risk_score must be in [0.0, 1.0]."""
        import app.scoring.predict as predict_module
        predict_module._model_artifact = mock_model_artifact

        request = ScoreRequest(
            transaction_id="TXN-TEST",
            amount=100.0,
            time=0.0,
            **{f"v{i}": 0.0 for i in range(1, 29)},
        )
        from app.scoring.predict import score_transaction
        response = score_transaction(request)
        assert 0.0 <= response.risk_score <= 1.0

    def test_score_response_schema(self, mock_model_artifact):
        import app.scoring.predict as predict_module
        predict_module._model_artifact = mock_model_artifact

        request = ScoreRequest(
            transaction_id="TXN-SCHEMA",
            amount=250.0,
            time=3600.0,
            **{f"v{i}": 0.1 for i in range(1, 29)},
        )
        from app.scoring.predict import score_transaction
        response = score_transaction(request)
        assert isinstance(response, ScoreResponse)
        assert response.transaction_id == "TXN-SCHEMA"
        assert isinstance(response.flagged, bool)
        assert isinstance(response.model_version, str)

    def test_flag_threshold(self, mock_model_artifact):
        """Mock returns 0.85 — should be flagged with default threshold 0.5."""
        import app.scoring.predict as predict_module
        predict_module._model_artifact = mock_model_artifact

        request = ScoreRequest(
            transaction_id="TXN-FLAG",
            amount=100.0,
            time=0.0,
            **{f"v{i}": 0.0 for i in range(1, 29)},
        )
        from app.scoring.predict import score_transaction
        response = score_transaction(request)
        assert response.flagged is True

    def test_score_returns_risk_factors_list(self, mock_model_artifact):
        import app.scoring.predict as predict_module
        predict_module._model_artifact = mock_model_artifact

        request = ScoreRequest(
            transaction_id="TXN-XAI",
            amount=200.0,
            time=100.0,
            **{f"v{i}": 0.0 for i in range(1, 29)},
        )
        from app.scoring.predict import score_transaction
        response = score_transaction(request)
        assert hasattr(response, "risk_factors")
        assert isinstance(response.risk_factors, list)
