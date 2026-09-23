"""Tests for the RAG investigation assistant."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from app.rag.generate import _format_case_context, generate_answer
from app.rag.ingest import format_case_as_text, ingest_cases
from app.rag.retriever import retrieve


@pytest.fixture
def chroma_client():
    """In-memory ChromaDB client for testing."""
    return chromadb.Client()


@pytest.fixture
def populated_collection(chroma_client, sample_cases):
    """A ChromaDB collection populated with sample cases."""
    count = ingest_cases(cases=sample_cases, chroma_client=chroma_client)
    assert count == len(sample_cases)
    collection = chroma_client.get_collection(
        name="fraud_cases",
    )
    return collection


class TestCaseIngestion:
    """Tests for case record ingestion."""

    def test_ingest_adds_cases(self, chroma_client, sample_cases):
        count = ingest_cases(cases=sample_cases, chroma_client=chroma_client)
        assert count == 3

    def test_format_case_as_text_includes_key_fields(self, sample_cases):
        text = format_case_as_text(sample_cases[0])
        assert "CASE-TEST-001" in text
        assert "John Doe" in text
        assert "johndoe@okicici" in text
        assert "50,000.00" in text
        assert "escalated" in text

    def test_format_case_as_text_includes_complaint(self, sample_cases):
        text = format_case_as_text(sample_cases[0])
        assert "unauthorized transaction" in text

    def test_ingest_from_missing_file_raises(self, chroma_client):
        with pytest.raises(FileNotFoundError):
            ingest_cases(
                cases_path=Path("nonexistent.json"),
                chroma_client=chroma_client,
            )


class TestRetrieval:
    """Tests for vector search."""

    def test_retrieval_returns_results(self, populated_collection):
        results = retrieve(
            query="unauthorized transaction flagged",
            top_k=3,
            collection=populated_collection,
        )
        assert len(results) > 0
        assert len(results) <= 3

    def test_retrieval_result_structure(self, populated_collection):
        results = retrieve(
            query="mule account network",
            top_k=1,
            collection=populated_collection,
        )
        assert len(results) == 1
        result = results[0]
        assert "case_id" in result
        assert "document" in result
        assert "score" in result
        assert "metadata" in result

    def test_retrieval_relevance(self, populated_collection):
        """Query about night-time should rank CASE-TEST-003 highly."""
        results = retrieve(
            query="night time transaction anomaly",
            top_k=3,
            collection=populated_collection,
        )
        case_ids = [r["case_id"] for r in results]
        assert "CASE-TEST-003" in case_ids

    def test_retrieval_score_bounded(self, populated_collection):
        results = retrieve(
            query="fraud investigation",
            top_k=3,
            collection=populated_collection,
        )
        for r in results:
            assert -1.0 <= r["score"] <= 1.0


class TestGeneration:
    """Tests for LLM answer generation."""

    def test_format_case_context_xml(self, sample_cases):
        retrieved = [
            {
                "case_id": c["case_id"],
                "document": format_case_as_text(c),
                "score": 0.9,
                "metadata": {"risk_score": c["risk_score"]},
            }
            for c in sample_cases[:2]
        ]
        context = _format_case_context(retrieved)
        assert "<context>" in context
        assert "</context>" in context
        assert 'id="CASE-TEST-001"' in context
        assert 'id="CASE-TEST-002"' in context

    def test_generate_empty_cases_returns_refusal(self):
        answer = generate_answer("What is the status?", retrieved_cases=[])
        assert "insufficient" in answer.lower()

    @patch("app.rag.generate._get_gemini_client")
    def test_generate_answer_calls_llm(self, mock_client_fn, sample_cases):
        """Verify the LLM is called with proper context."""
        mock_interaction = MagicMock()
        mock_interaction.output_text = "The account [Case: CASE-TEST-001] has risk 0.92."
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client_fn.return_value = mock_client

        retrieved = [
            {
                "case_id": sample_cases[0]["case_id"],
                "document": format_case_as_text(sample_cases[0]),
                "score": 0.95,
                "metadata": {"risk_score": sample_cases[0]["risk_score"]},
            }
        ]
        answer = generate_answer("What is the risk for John Doe?", retrieved)
        assert "CASE-TEST-001" in answer
        mock_client.interactions.create.assert_called_once()

    @patch("app.rag.generate._get_gemini_client")
    def test_generate_fallback_on_error(self, mock_client_fn, sample_cases):
        """If LLM fails, should return raw cases as fallback."""
        mock_client_fn.side_effect = Exception("API error")

        retrieved = [
            {
                "case_id": sample_cases[0]["case_id"],
                "document": format_case_as_text(sample_cases[0]),
                "score": 0.95,
                "metadata": {"risk_score": sample_cases[0]["risk_score"]},
            }
        ]
        answer = generate_answer("test query", retrieved)
        assert "LLM unavailable" in answer
        assert "CASE-TEST-001" in answer
