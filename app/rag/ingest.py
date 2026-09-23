"""Ingest synthetic case records into ChromaDB vector store.

Each case record is treated as a single chunk (they're short enough)
and embedded using sentence-transformers all-MiniLM-L6-v2.

Usage:
    python -m app.rag.ingest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
import structlog
from chromadb.utils import embedding_functions

from app.config import get_settings

logger = structlog.get_logger(__name__)

CASES_PATH = Path("data/synthetic_cases.json")


def _get_embedding_function() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """Create the sentence-transformer embedding function.

    Uses all-MiniLM-L6-v2: 384-dim, ~80MB, runs on CPU.
    Note: 256 wordpiece token limit — cases must be kept under ~200 words.
    """
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2",
        device="cpu",
        normalize_embeddings=True,
    )


def _get_chroma_collection(
    client: chromadb.ClientAPI | None = None,
) -> chromadb.Collection:
    """Get or create the fraud_cases ChromaDB collection."""
    settings = get_settings()
    if client is None:
        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)

    return client.get_or_create_collection(
        name="fraud_cases",
        embedding_function=_get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def format_case_as_text(case: dict) -> str:
    """Flatten a case record into a searchable text string.

    Includes all key fields so semantic search can match on any aspect.
    """
    linked = ", ".join(case.get("linked_accounts", [])) or "none"
    return (
        f"Case ID: {case['case_id']}\n"
        f"Transaction ID: {case['transaction_id']}\n"
        f"Account Holder: {case['account_holder']}\n"
        f"Account Number: {case['account_number']}\n"
        f"UPI ID: {case['upi_id']}\n"
        f"Risk Score: {case['risk_score']}\n"
        f"Amount: ₹{case['amount']:,.2f}\n"
        f"Status: {case['status']}\n"
        f"Timestamp: {case['timestamp']}\n"
        f"Linked Accounts: {linked}\n\n"
        f"Complaint: {case['complaint_text']}\n\n"
        f"Investigator Notes: {case['investigator_notes']}"
    )


def ingest_cases(
    cases: list[dict] | None = None,
    cases_path: Path | None = None,
    chroma_client: chromadb.ClientAPI | None = None,
) -> int:
    """Ingest case records into the ChromaDB vector store.

    Args:
        cases: List of case record dicts. If None, loads from cases_path.
        cases_path: Path to JSON file. Defaults to data/synthetic_cases.json.
        chroma_client: Optional ChromaDB client (for testing).

    Returns:
        Number of cases ingested.
    """
    if cases is None:
        path = cases_path or CASES_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"Cases file not found at {path}. "
                "Run 'python -m app.data.synthetic_cases' first."
            )
        with open(path, "r", encoding="utf-8") as f:
            cases = json.load(f)

    collection = _get_chroma_collection(chroma_client)

    # Batch insert
    ids = []
    documents = []
    metadatas = []

    for case in cases:
        ids.append(case["case_id"])
        documents.append(format_case_as_text(case))
        metadatas.append({
            "case_id": case["case_id"],
            "risk_score": float(case["risk_score"]),
            "status": case["status"],
            "account_number": case["account_number"],
            "upi_id": case["upi_id"],
            "amount": float(case["amount"]),
        })

    # ChromaDB handles batching internally; upsert all at once
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )

    logger.info("cases_ingested", count=len(cases))
    print(f"Ingested {len(cases)} cases into ChromaDB")
    return len(cases)


if __name__ == "__main__":
    count = ingest_cases()
    print(f"Done. {count} cases indexed.")
