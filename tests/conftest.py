"""Shared test fixtures for fraud-copilot tests."""
from __future__ import annotations

from typing import Any, Generator

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

# --- Sample transaction data ---

@pytest.fixture
def sample_transaction_dict() -> dict[str, Any]:
    """A valid transaction payload matching ScoreRequest."""
    features = {f"v{i}": 0.0 for i in range(1, 29)}
    features.update({
        "transaction_id": "TXN-TEST-001",
        "amount": 149.99,
        "time": 43200.0,  # 12 hours from start
    })
    return features


@pytest.fixture
def sample_transaction_df() -> pd.DataFrame:
    """A single-row DataFrame with all features."""
    data = {f"V{i}": [0.0] for i in range(1, 29)}
    data["Time"] = [43200.0]
    data["Amount"] = [149.99]
    return pd.DataFrame(data)


@pytest.fixture
def sample_dataset() -> pd.DataFrame:
    """A small synthetic dataset for testing feature engineering."""
    np.random.seed(42)
    n = 100
    data = {f"V{i}": np.random.randn(n) for i in range(1, 29)}
    data["Time"] = np.random.uniform(0, 172800, n)
    data["Amount"] = np.random.exponential(50, n)
    data["Class"] = np.zeros(n, dtype=int)
    data["Class"][:5] = 1  # 5% fraud for testing
    return pd.DataFrame(data)


# --- Sample case records ---

@pytest.fixture
def sample_cases() -> list[dict[str, Any]]:
    """Sample case records for RAG testing."""
    return [
        {
            "case_id": "CASE-TEST-001",
            "transaction_id": "TXN-001",
            "account_holder": "John Doe",
            "account_number": "123456789012",
            "upi_id": "johndoe@okicici",
            "card_last4": "4567",
            "phone": "+1-555-0101",
            "email": "john@example.com",
            "address": "123 Main St, Mumbai",
            "risk_score": 0.92,
            "amount": 50000.00,
            "timestamp": "2024-01-15T14:30:00",
            "complaint_text": "Customer John Doe reported unauthorized transaction of \u20b950,000.00 on 2024-01-15. Card ending 4567 was used at Acme Corp.",
            "investigator_notes": "Cross-referenced transaction with merchant database. Merchant Acme Corp has 12 prior fraud reports. Recommend escalation to L2.",
            "status": "escalated",
            "linked_accounts": ["987654321098"],
            "assigned_to": "INV-101",
            "created_at": "2024-01-15T16:00:00",
        },
        {
            "case_id": "CASE-TEST-002",
            "transaction_id": "TXN-002",
            "account_holder": "Jane Smith",
            "account_number": "987654321098",
            "upi_id": "janesmith@ybl",
            "card_last4": "8901",
            "phone": "+1-555-0202",
            "email": "jane@example.com",
            "address": "456 Oak Ave, Delhi",
            "risk_score": 0.75,
            "amount": 15000.00,
            "timestamp": "2024-01-16T09:15:00",
            "complaint_text": "Alert triggered: high-risk transaction of \u20b915,000.00 from account 987654321098 via UPI ID janesmith@ybl.",
            "investigator_notes": "UPI ID janesmith@ybl linked to 5 accounts across 3 banks. Pattern consistent with mule account network.",
            "status": "open",
            "linked_accounts": ["123456789012", "555666777888"],
            "assigned_to": "INV-102",
            "created_at": "2024-01-16T11:00:00",
        },
        {
            "case_id": "CASE-TEST-003",
            "transaction_id": "TXN-003",
            "account_holder": "Bob Wilson",
            "account_number": "555666777888",
            "upi_id": "bobw@paytm",
            "card_last4": "2345",
            "phone": "+1-555-0303",
            "email": "bob@example.com",
            "address": "789 Elm St, Bangalore",
            "risk_score": 0.88,
            "amount": 75000.00,
            "timestamp": "2024-01-17T22:45:00",
            "complaint_text": "Night-time transaction of \u20b975,000.00 flagged for account 555666777888. Transaction at 22:45 falls outside customer's typical activity window.",
            "investigator_notes": "Behavioral analytics confirm anomaly: average transaction value for this account is \u20b92,500.00; flagged transaction is 30.0x the average.",
            "status": "under_review",
            "linked_accounts": [],
            "assigned_to": "INV-103",
            "created_at": "2024-01-18T01:00:00",
        },
    ]


# --- Mock model ---

class MockFraudModel:
    """A mock sklearn pipeline for testing without a real model."""

    def predict_proba(self, X):
        """Return a fixed fraud probability."""
        n = len(X) if hasattr(X, '__len__') else 1
        return np.array([[0.15, 0.85]] * n)

    def predict(self, X):
        """Return predicted class."""
        n = len(X) if hasattr(X, '__len__') else 1
        return np.array([1] * n)


@pytest.fixture
def mock_model_artifact() -> dict[str, Any]:
    """A mock model artifact dict matching joblib format."""
    return {
        "pipeline": MockFraudModel(),
        "threshold": 0.5,
        "model_name": "MockXGBoost",
        "feature_names": [f"V{i}" for i in range(1, 29)] + ["Time", "Amount"],
    }


# --- FastAPI test client ---

@pytest.fixture
def client(mock_model_artifact) -> Generator[TestClient, None, None]:
    """Create a TestClient with mocked model."""
    import app.scoring.predict as predict_module

    # Patch the model cache
    original = predict_module._model_artifact
    predict_module._model_artifact = mock_model_artifact

    from app.main import app
    with TestClient(app) as c:
        yield c

    predict_module._model_artifact = original
