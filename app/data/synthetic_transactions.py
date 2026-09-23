"""Utility to generate synthetic creditcard transaction data for training."""
from pathlib import Path

import numpy as np
import pandas as pd


def generate_synthetic_transactions(
    n_samples: int = 10000,
    n_fraud: int = 50,
    output_path: Path | str = "data/raw/creditcard.csv"
) -> Path:
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    np.random.seed(42)
    n_legit = n_samples - n_fraud

    # Legit samples
    v_legit = np.random.randn(n_legit, 28)
    time_legit = np.random.uniform(0, 172800, n_legit)
    amount_legit = np.random.exponential(scale=45.0, size=n_legit) + 1.0

    # Fraud samples (simulate Kaggle PCA correlation patterns)
    v_fraud = np.random.randn(n_fraud, 28)
    v_fraud[:, 13] -= 3.0  # V14
    v_fraud[:, 11] -= 2.5  # V12
    v_fraud[:, 9] -= 2.5   # V10
    v_fraud[:, 16] -= 2.0  # V17
    v_fraud[:, 3] += 2.5   # V4
    v_fraud[:, 10] += 2.0  # V11
    time_fraud = np.random.uniform(0, 172800, n_fraud)
    amount_fraud = np.random.exponential(scale=120.0, size=n_fraud) + 10.0

    V = np.vstack([v_legit, v_fraud])
    time = np.concatenate([time_legit, time_fraud])
    amount = np.concatenate([amount_legit, amount_fraud])
    target = np.array([0] * n_legit + [1] * n_fraud)

    indices = np.arange(n_samples)
    np.random.shuffle(indices)

    data = {"Time": time[indices]}
    for i in range(28):
        data[f"V{i+1}"] = V[indices, i]
    data["Amount"] = amount[indices]
    data["Class"] = target[indices]

    df = pd.DataFrame(data)
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} transactions ({df['Class'].sum()} fraud) at {out_path}")
    return out_path

if __name__ == "__main__":
    generate_synthetic_transactions()
