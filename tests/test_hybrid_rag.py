"""Tests for BM25 sparse search, entity-preserving tokenization, and Reciprocal Rank Fusion (RRF)."""

from app.rag.hybrid_retriever import (
    BM25Index,
    hybrid_retrieve,
    reciprocal_rank_fusion,
    tokenize_financial_text,
)


class TestHybridRAG:

    def test_financial_tokenizer_preserves_identifiers(self):
        text = "Alert on case CASE-2F257CB0 with account 051204618723 and UPI sudiksha01@ibl at 192.168.1.55"
        tokens = tokenize_financial_text(text)
        assert "case-2f257cb0" in tokens
        assert "051204618723" in tokens
        assert "sudiksha01@ibl" in tokens
        assert "alert" in tokens

    def test_bm25_exact_identifier_matching(self):
        sample_cases = [
            {
                "case_id": "CASE-001",
                "account_number": "111122223333",
                "upi_id": "target_mule@okaxis",
                "complaint_text": "Unauthorized wire transfer reported by customer.",
            },
            {
                "case_id": "CASE-002",
                "account_number": "444455556666",
                "upi_id": "legit_user@okicici",
                "complaint_text": "ATM withdrawal limit exceeded at midnight.",
            },
            {
                "case_id": "CASE-003",
                "account_number": "777788889999",
                "upi_id": "target_mule@okaxis",
                "complaint_text": "Secondary transfer to known fraudulent UPI handle.",
            },
        ]

        bm25 = BM25Index()
        bm25.fit(sample_cases)

        # Search for exact UPI handle
        results = bm25.search("target_mule@okaxis", top_k=5)
        assert len(results) == 2
        case_ids = [r["case_id"] for r in results]
        assert "CASE-001" in case_ids
        assert "CASE-003" in case_ids
        assert "CASE-002" not in case_ids

        # Search for exact account number
        results_acc = bm25.search("444455556666", top_k=5)
        assert len(results_acc) == 1
        assert results_acc[0]["case_id"] == "CASE-002"

    def test_reciprocal_rank_fusion_logic(self):
        dense_results = [
            {"case_id": "CASE-A", "document": "Doc A", "score": 0.95},
            {"case_id": "CASE-B", "document": "Doc B", "score": 0.85},
            {"case_id": "CASE-C", "document": "Doc C", "score": 0.75},
        ]
        sparse_results = [
            {"case_id": "CASE-B", "document": "Doc B", "score": 4.5},
            {"case_id": "CASE-D", "document": "Doc D", "score": 3.8},
            {"case_id": "CASE-A", "document": "Doc A", "score": 2.1},
        ]

        # Case B appears at rank 2 in dense and rank 1 in sparse -> should get top combined RRF score
        fused = reciprocal_rank_fusion(dense_results, sparse_results, top_k=4, k_rrf=60)
        assert len(fused) == 4
        # Top 1 should be CASE-B
        assert fused[0]["case_id"] == "CASE-B"
        assert fused[0]["retrieval_method"] == "hybrid_rrf"
        assert fused[0]["score"] > 0

    def test_hybrid_retrieve_graceful_fallbacks(self):
        from unittest.mock import patch
        sample_cases = [
            {"case_id": "CASE-10", "complaint_text": "Compromised card detected in Bengaluru."},
        ]
        bm25 = BM25Index()
        bm25.fit(sample_cases)

        # When dense retrieval is unavailable or returns empty, returns BM25 sparse results
        with patch("app.rag.hybrid_retriever.dense_retrieve", return_value=[]):
            results = hybrid_retrieve("Bengaluru", top_k=2, collection=None, bm25_index=bm25)
            assert len(results) >= 1
            assert results[0]["case_id"] == "CASE-10"

