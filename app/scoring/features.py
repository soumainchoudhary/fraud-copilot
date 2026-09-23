"""Feature engineering for credit card fraud detection.

Handles the Kaggle Credit Card Fraud dataset (PCA-anonymized V1-V28 + Time + Amount).
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import FunctionTransformer, RobustScaler

PCA_FEATURES = [f"V{i}" for i in range(1, 29)]


def _cyclical_time_encoding(df: pd.DataFrame) -> pd.DataFrame:
    """Convert raw Time (seconds) to cyclical hour-of-day encoding.

    The dataset's Time column is seconds elapsed from the first transaction.
    We convert to hour-of-day (mod 86400 / 3600) then encode as sin/cos
    to capture circadian fraud patterns without discontinuity at midnight.
    """
    result = pd.DataFrame(index=df.index)
    hours = (df["Time"] % 86400) / 3600
    result["sin_time"] = np.sin(2 * np.pi * hours / 24)
    result["cos_time"] = np.cos(2 * np.pi * hours / 24)
    return result


def build_feature_transformer() -> ColumnTransformer:
    """Build the feature transformation pipeline.

    - Amount: RobustScaler (handles extreme outliers, median ~€22, max ~€25,691)
    - Time: Cyclical sin/cos hour-of-day encoding
    - V1-V28: Passed through as-is (already PCA-transformed, do NOT re-scale)

    Returns:
        ColumnTransformer ready to fit on training data.
    """
    return ColumnTransformer(
        transformers=[
            ("amount_scaler", RobustScaler(), ["Amount"]),
            (
                "time_encoder",
                FunctionTransformer(_cyclical_time_encoding, validate=False),
                ["Time"],
            ),
            ("pca_passthrough", "passthrough", PCA_FEATURES),
        ],
        remainder="drop",
    )


def get_feature_names() -> list[str]:
    """Return the ordered list of feature names after transformation."""
    return ["scaled_amount", "sin_time", "cos_time"] + PCA_FEATURES


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and validate the raw dataset.

    - Drops duplicate rows (~1,081 in the Kaggle dataset)
    - Validates expected columns exist
    - Returns cleaned DataFrame
    """
    expected_cols = {"Time", "Amount", "Class"} | {f"V{i}" for i in range(1, 29)}
    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing expected columns: {missing}")

    original_len = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    dropped = original_len - len(df)
    if dropped > 0:
        print(f"Dropped {dropped} duplicate rows ({original_len} → {len(df)})")

    return df
