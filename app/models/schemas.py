"""Pydantic v2 request/response models for the Fraud Copilot API.

Defines the API contract for /score, /ask, and /health endpoints.
"""
from typing import Optional

from pydantic import BaseModel, Field

# --- Health ---

class HealthResponse(BaseModel):
    """Response for GET /health."""
    status: str = "ok"


# --- Scoring ---

class ScoreRequest(BaseModel):
    """Request body for POST /score.

    Contains the 30 features from the Kaggle Credit Card Fraud dataset:
    V1-V28 (PCA-transformed), Time, and Amount.
    Enforces strict production validation bounds to prevent buffer overflows and injection.
    """
    transaction_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9_\-\.]{1,64}$",
        max_length=64,
        description="Unique transaction identifier (alphanumeric, -, _, .)",
    )
    amount: float = Field(..., ge=0.0, le=10_000_000.0, description="Transaction amount in local currency")
    time: float = Field(..., ge=0.0, le=1_000_000_000.0, description="Seconds elapsed from first transaction")
    v1: float = Field(..., ge=-100.0, le=100.0, alias="v1")
    v2: float = Field(..., ge=-100.0, le=100.0, alias="v2")
    v3: float = Field(..., ge=-100.0, le=100.0, alias="v3")
    v4: float = Field(..., ge=-100.0, le=100.0, alias="v4")
    v5: float = Field(..., ge=-100.0, le=100.0, alias="v5")
    v6: float = Field(..., ge=-100.0, le=100.0, alias="v6")
    v7: float = Field(..., ge=-100.0, le=100.0, alias="v7")
    v8: float = Field(..., ge=-100.0, le=100.0, alias="v8")
    v9: float = Field(..., ge=-100.0, le=100.0, alias="v9")
    v10: float = Field(..., ge=-100.0, le=100.0, alias="v10")
    v11: float = Field(..., ge=-100.0, le=100.0, alias="v11")
    v12: float = Field(..., ge=-100.0, le=100.0, alias="v12")
    v13: float = Field(..., ge=-100.0, le=100.0, alias="v13")
    v14: float = Field(..., ge=-100.0, le=100.0, alias="v14")
    v15: float = Field(..., ge=-100.0, le=100.0, alias="v15")
    v16: float = Field(..., ge=-100.0, le=100.0, alias="v16")
    v17: float = Field(..., ge=-100.0, le=100.0, alias="v17")
    v18: float = Field(..., ge=-100.0, le=100.0, alias="v18")
    v19: float = Field(..., ge=-100.0, le=100.0, alias="v19")
    v20: float = Field(..., ge=-100.0, le=100.0, alias="v20")
    v21: float = Field(..., ge=-100.0, le=100.0, alias="v21")
    v22: float = Field(..., ge=-100.0, le=100.0, alias="v22")
    v23: float = Field(..., ge=-100.0, le=100.0, alias="v23")
    v24: float = Field(..., ge=-100.0, le=100.0, alias="v24")
    v25: float = Field(..., ge=-100.0, le=100.0, alias="v25")
    v26: float = Field(..., ge=-100.0, le=100.0, alias="v26")
    v27: float = Field(..., ge=-100.0, le=100.0, alias="v27")
    v28: float = Field(..., ge=-100.0, le=100.0, alias="v28")

    model_config = {"populate_by_name": True}


class RiskFactor(BaseModel):
    """An explainable AI feature contribution factor."""
    feature: str = Field(..., description="Feature identifier (e.g. V14, Amount)")
    contribution: float = Field(..., description="Directional risk attribution score")
    direction: str = Field(default="risk_increasing", description="'risk_increasing' or 'risk_decreasing'")
    description: str = Field(..., description="Human-interpretable forensic reason")


class ScoreResponse(BaseModel):
    """Response body for POST /score."""
    transaction_id: str
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Fraud probability")
    flagged: bool = Field(..., description="True if risk_score >= threshold")
    model_version: str
    risk_factors: list[RiskFactor] = Field(default_factory=list, description="Top contributing factors")


class BatchScoreRequest(BaseModel):
    """Request body for POST /score/batch."""
    transactions: list[ScoreRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of transactions to score (max 100 per batch)",
    )


class BatchScoreResponse(BaseModel):
    """Response body for POST /score/batch."""
    total_processed: int
    total_flagged: int
    total_latency_ms: float
    results: list[ScoreResponse]


# --- RAG ---

class AskRequest(BaseModel):
    """Request body for POST /ask."""
    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="Natural language question (max 1000 characters)",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="Number of cases to retrieve")


class Source(BaseModel):
    """A single retrieved case source for the RAG response."""
    case_id: str
    snippet: str = Field(..., description="Excerpt from the case record")
    score: float = Field(..., description="Retrieval similarity score")


class AskResponse(BaseModel):
    """Response body for POST /ask."""
    answer: str = Field(..., description="Generated answer with case citations")
    sources: list[Source] = Field(default_factory=list)


# --- Case Management ---

class CaseItem(BaseModel):
    """A complete investigation case record."""
    case_id: str
    transaction_id: str
    account_holder: str
    account_number: str
    upi_id: str
    card_last4: str
    phone: str
    email: str
    address: str
    risk_score: float
    amount: float
    timestamp: str
    complaint_text: str
    investigator_notes: str
    status: str
    linked_accounts: list[str] = Field(default_factory=list)
    assigned_to: str
    created_at: str


class CaseListResponse(BaseModel):
    """Paginated list of investigation cases."""
    total: int
    page: int
    page_size: int
    items: list[CaseItem]


class CaseStatsResponse(BaseModel):
    """Summary statistics across all stored cases."""
    total_cases: int
    open_cases: int
    escalated_cases: int
    under_review_cases: int
    resolved_cases: int
    average_risk_score: float


class CaseUpdateRequest(BaseModel):
    """Request body for PATCH /cases/{case_id}."""
    status: Optional[str] = Field(
        None,
        pattern=r"^(open|under_review|escalated|resolved|closed)$",
        description="New case status: open, under_review, escalated, resolved, closed",
    )
    investigator_notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="New investigator note to append to existing notes",
    )
    assigned_to: Optional[str] = Field(
        None,
        max_length=64,
        description="Updated investigator assignment (e.g. INV-105)",
    )

