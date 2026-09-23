"""Offline model training script for fraud detection.

Run once to train and persist the model:
    python -m app.scoring.train

Expects data/raw/creditcard.csv to exist.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from app.scoring.features import build_feature_transformer, prepare_dataframe

# --- Configuration ---
DATA_PATH = Path("data/raw/creditcard.csv")
MODEL_DIR = Path("models")
MODEL_PATH = MODEL_DIR / "xgboost_fraud_v1.joblib"


def load_data() -> pd.DataFrame:
    """Load and clean the credit card fraud dataset."""
    if not DATA_PATH.exists():
        print(f"ERROR: Dataset not found at {DATA_PATH}")
        print("Download from: https://www.kaggle.com/mlg-ulb/creditcardfraud")
        print(f"Place creditcard.csv in {DATA_PATH.parent}/")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)
    df = prepare_dataframe(df)
    return df


def print_eda_summary(df: pd.DataFrame) -> None:
    """Print basic EDA statistics."""
    total = len(df)
    fraud = df["Class"].sum()
    legit = total - fraud
    print("\n" + "=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)
    print(f"Total transactions:  {total:,}")
    print(f"Legitimate:          {legit:,} ({legit/total*100:.2f}%)")
    print(f"Fraudulent:          {fraud:,} ({fraud/total*100:.3f}%)")
    print(f"Imbalance ratio:     1:{legit//fraud}")
    print("\nAmount stats:")
    print(f"  Mean:   €{df['Amount'].mean():.2f}")
    print(f"  Median: €{df['Amount'].median():.2f}")
    print(f"  Max:    €{df['Amount'].max():.2f}")
    print(f"  Fraud mean:   €{df[df['Class']==1]['Amount'].mean():.2f}")
    print(f"  Legit mean:   €{df[df['Class']==0]['Amount'].mean():.2f}")
    print("=" * 60)


def evaluate_model(
    name: str,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> dict:
    """Evaluate a model and print metrics.

    NOTE: Accuracy is intentionally excluded — it's meaningless on data
    this imbalanced (a dummy classifier achieves 99.83% accuracy by
    predicting all-legitimate).
    """
    y_pred = (y_prob >= threshold).astype(int)

    roc_auc = roc_auc_score(y_true, y_prob)
    pr_auc = average_precision_score(y_true, y_prob)
    f1 = f1_score(y_true, y_pred)

    print(f"\n{'─' * 60}")
    print(f"MODEL: {name}  (threshold={threshold:.2f})")
    print(f"{'─' * 60}")
    print(f"  ROC-AUC:  {roc_auc:.4f}")
    print(f"  PR-AUC:   {pr_auc:.4f}  ← primary metric")
    print(f"  F1:       {f1:.4f}")
    print("\n  Classification Report:")
    print(classification_report(y_true, y_pred, target_names=["Legit", "Fraud"]))

    return {"roc_auc": roc_auc, "pr_auc": pr_auc, "f1": f1, "threshold": threshold}


def find_optimal_threshold(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Find the threshold that maximizes F1 on the precision-recall curve.

    On heavily imbalanced data the optimal threshold is typically 0.05–0.20,
    far below the naive 0.50 default.
    """
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_prob)
    # Compute F1 for each threshold (exclude last point where P=1, R=0)
    f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (
        precisions[:-1] + recalls[:-1] + 1e-10
    )
    best_idx = np.argmax(f1_scores)
    best_threshold = float(thresholds[best_idx])
    print(f"  Optimal threshold: {best_threshold:.4f} (F1={f1_scores[best_idx]:.4f})")
    return best_threshold


def train() -> None:
    """Main training pipeline."""
    # 1. Load and clean data
    df = load_data()
    print_eda_summary(df)

    # 2. Split features and target
    X = df.drop(columns=["Class"])
    y = df["Class"].values

    # 3. Stratified train/test split (preserves 0.17% fraud ratio)
    splitter = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    print(f"\nTrain: {len(X_train):,} samples ({y_train.sum()} fraud)")
    print(f"Test:  {len(X_test):,} samples ({y_test.sum()} fraud)")

    # 4. Build feature transformer
    transformer = build_feature_transformer()

    # 5. Baseline: Logistic Regression
    print("\n" + "=" * 60)
    print("TRAINING BASELINE: Logistic Regression")
    print("=" * 60)
    lr_pipeline = Pipeline([
        ("features", transformer),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
            solver="lbfgs",
        )),
    ])
    lr_pipeline.fit(X_train, y_train)
    lr_probs = lr_pipeline.predict_proba(X_test)[:, 1]
    lr_threshold = find_optimal_threshold(y_test, lr_probs)
    lr_metrics = evaluate_model("LogisticRegression", y_test, lr_probs, lr_threshold)

    # 6. Primary: XGBoost with scale_pos_weight
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    scale_pos = n_neg / n_pos

    print("\n" + "=" * 60)
    print(f"TRAINING PRIMARY: XGBoost (scale_pos_weight={scale_pos:.0f})")
    print("=" * 60)
    xgb_pipeline = Pipeline([
        ("features", transformer),
        ("classifier", XGBClassifier(
            scale_pos_weight=scale_pos,
            max_depth=4,
            learning_rate=0.02,
            n_estimators=500,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=10,
            eval_metric="aucpr",
            random_state=42,
            use_label_encoder=False,
            verbosity=0,
        )),
    ])
    xgb_pipeline.fit(X_train, y_train)
    xgb_probs = xgb_pipeline.predict_proba(X_test)[:, 1]
    xgb_threshold = find_optimal_threshold(y_test, xgb_probs)
    xgb_metrics = evaluate_model("XGBoost", y_test, xgb_probs, xgb_threshold)

    # 7. Compare and select winner
    print("\n" + "=" * 60)
    print("MODEL COMPARISON (primary metric: PR-AUC)")
    print("=" * 60)
    print(f"  {'Model':<25} {'ROC-AUC':>10} {'PR-AUC':>10} {'F1':>10}")
    print(f"  {'─'*25} {'─'*10} {'─'*10} {'─'*10}")
    print(f"  {'LogisticRegression':<25} {lr_metrics['roc_auc']:>10.4f} {lr_metrics['pr_auc']:>10.4f} {lr_metrics['f1']:>10.4f}")
    print(f"  {'XGBoost':<25} {xgb_metrics['roc_auc']:>10.4f} {xgb_metrics['pr_auc']:>10.4f} {xgb_metrics['f1']:>10.4f}")

    winner = xgb_pipeline if xgb_metrics["pr_auc"] >= lr_metrics["pr_auc"] else lr_pipeline
    winner_name = "XGBoost" if winner is xgb_pipeline else "LogisticRegression"
    winner_threshold = xgb_threshold if winner is xgb_pipeline else lr_threshold

    print(f"\n  ✓ Winner: {winner_name} (PR-AUC={max(xgb_metrics['pr_auc'], lr_metrics['pr_auc']):.4f})")

    # 8. Save model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    artifact = {
        "pipeline": winner,
        "threshold": winner_threshold,
        "model_name": winner_name,
        "feature_names": [f"V{i}" for i in range(1, 29)] + ["Time", "Amount"],
    }
    joblib.dump(artifact, MODEL_PATH)
    print(f"\n  Model saved to {MODEL_PATH}")
    print(f"  Optimal threshold: {winner_threshold:.4f}")


if __name__ == "__main__":
    train()
