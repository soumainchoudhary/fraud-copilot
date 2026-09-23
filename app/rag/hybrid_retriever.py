"""Hybrid Retriever combining BM25 Sparse Keyword Search with Dense Vector ChromaDB via RRF."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

import structlog

from app.rag.retriever import retrieve as dense_retrieve

logger = structlog.get_logger(__name__)


def tokenize_financial_text(text: str) -> list[str]:
    """Tokenize text preserving case IDs, UPI handles, emails, account numbers, and words."""
    if not text:
        return []
    # Match UPIs/emails (e.g. name@bank), case IDs, txn IDs, numbers, and words
    pattern = re.compile(r"[A-Za-z0-9_\-\.]+@[A-Za-z0-9_\-\.]+|[A-Za-z0-9_\-]{2,}|[0-9]+")
    tokens = pattern.findall(text)
    return [t.lower() for t in tokens if len(t) >= 2]


class BM25Index:
    """In-memory BM25 Okapi search index for forensic case records."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: list[dict[str, Any]] = []
        self.doc_lengths: list[int] = []
        self.avg_doc_len: float = 0.0
        self.term_freqs: list[Counter] = []
        self.doc_freqs: dict[str, int] = defaultdict(int)
        self.idf: dict[str, float] = {}
        self.doc_count: int = 0

    def fit(self, docs: list[dict[str, Any]]) -> None:
        """Index a list of documents. Each doc must have 'case_id' and 'document' (or 'text')."""
        self.documents = docs
        self.doc_count = len(docs)
        self.term_freqs = []
        self.doc_freqs = defaultdict(int)
        self.doc_lengths = []

        total_length = 0
        for doc in docs:
            content = doc.get("document") or doc.get("complaint_text", "")
            # Also append key identifiers to doc text for exact matching
            identifiers = " ".join([
                str(doc.get("case_id", "")),
                str(doc.get("transaction_id", "")),
                str(doc.get("account_number", "")),
                str(doc.get("upi_id", "")),
                str(doc.get("account_holder", "")),
            ])
            full_text = f"{identifiers} {content} {doc.get('investigator_notes', '')}"

            tokens = tokenize_financial_text(full_text)
            length = len(tokens)
            self.doc_lengths.append(length)
            total_length += length

            tf = Counter(tokens)
            self.term_freqs.append(tf)
            for token in tf.keys():
                self.doc_freqs[token] += 1

        self.avg_doc_len = (total_length / self.doc_count) if self.doc_count > 0 else 0.0

        # Calculate Okapi BM25 Robertson-Spärck Jones IDF
        self.idf = {}
        for token, df in self.doc_freqs.items():
            self.idf[token] = math.log(((self.doc_count - df + 0.5) / (df + 0.5)) + 1.0)

        logger.info("bm25_index_built", doc_count=self.doc_count, vocab_size=len(self.idf))

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Score documents against query string using BM25."""
        if not self.documents or not query.strip():
            return []

        query_tokens = tokenize_financial_text(query)
        if not query_tokens:
            return []

        scores: list[tuple[int, float]] = []

        for idx in range(self.doc_count):
            tf = self.term_freqs[idx]
            doc_len = self.doc_lengths[idx]
            len_norm = 1.0 - self.b + self.b * (doc_len / (self.avg_doc_len or 1.0))

            doc_score = 0.0
            for token in query_tokens:
                if token in tf and token in self.idf:
                    count = tf[token]
                    term_score = self.idf[token] * ((count * (self.k1 + 1.0)) / (count + self.k1 * len_norm))
                    doc_score += term_score

            if doc_score > 0.0:
                scores.append((idx, doc_score))

        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        results = []
        for idx, score in top_results:
            orig = self.documents[idx]
            results.append({
                "case_id": orig.get("case_id"),
                "document": orig.get("document") or orig.get("complaint_text", ""),
                "score": round(score, 4),
                "metadata": orig.get("metadata") or orig,
            })
        return results


_global_bm25: BM25Index | None = None


def get_bm25_index() -> BM25Index:
    """Retrieve or build the global singleton BM25 index from case records."""
    global _global_bm25
    if _global_bm25 is not None and _global_bm25.doc_count > 0:
        return _global_bm25

    _global_bm25 = BM25Index()
    cases_file = Path("data/synthetic_cases.json")
    if cases_file.exists():
        try:
            with open(cases_file, "r", encoding="utf-8") as f:
                cases = json.load(f)
            _global_bm25.fit(cases)
        except Exception as e:
            logger.error("failed_initializing_bm25_from_file", error=str(e))
    return _global_bm25


def reciprocal_rank_fusion(
    dense_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    top_k: int = 5,
    k_rrf: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[dict[str, Any]]:
    """Combine dense and sparse search rankings using Reciprocal Rank Fusion (RRF).

    Formula: RRF_Score(d) = sum_{m in {dense, bm25}} weight_m / (k_rrf + rank_m(d))
    """
    fused_scores: dict[str, float] = defaultdict(float)
    doc_lookup: dict[str, dict[str, Any]] = {}

    # Rank positions are 1-indexed
    for rank, item in enumerate(dense_results, start=1):
        cid = item.get("case_id", "")
        if cid:
            fused_scores[cid] += dense_weight / (k_rrf + rank)
            if cid not in doc_lookup:
                doc_lookup[cid] = item

    for rank, item in enumerate(sparse_results, start=1):
        cid = item.get("case_id", "")
        if cid:
            fused_scores[cid] += sparse_weight / (k_rrf + rank)
            if cid not in doc_lookup:
                doc_lookup[cid] = item

    # Sort candidates by combined RRF score descending
    sorted_cids = sorted(fused_scores.keys(), key=lambda cid: fused_scores[cid], reverse=True)

    results: list[dict[str, Any]] = []
    for cid in sorted_cids[:top_k]:
        item = doc_lookup[cid]
        results.append({
            "case_id": cid,
            "document": item.get("document", ""),
            "score": round(fused_scores[cid], 6),
            "metadata": item.get("metadata", {}),
            "retrieval_method": "hybrid_rrf",
        })

    return results


def hybrid_retrieve(
    query: str,
    top_k: int = 5,
    collection: Any = None,
    bm25_index: Optional[BM25Index] = None,
    k_rrf: int = 60,
) -> list[dict[str, Any]]:
    """Execute hybrid dense + sparse retrieval with Reciprocal Rank Fusion."""
    # 1. Sparse BM25 Search
    bm25 = bm25_index or get_bm25_index()
    sparse_results = bm25.search(query, top_k=top_k * 2)

    # 2. Dense Vector ChromaDB Search
    try:
        dense_results = dense_retrieve(query, top_k=top_k * 2, collection=collection)
    except Exception as e:
        logger.warning("dense_retrieval_failed_fallback_to_sparse", error=str(e))
        dense_results = []

    # 3. Reciprocal Rank Fusion
    if dense_results and sparse_results:
        fused = reciprocal_rank_fusion(dense_results, sparse_results, top_k=top_k, k_rrf=k_rrf)
    elif dense_results:
        fused = dense_results[:top_k]
    elif sparse_results:
        fused = sparse_results[:top_k]
    else:
        fused = []

    logger.info(
        "hybrid_retrieval_completed",
        query=query[:60],
        dense_hits=len(dense_results),
        sparse_hits=len(sparse_results),
        fused_returned=len(fused),
    )
    return fused
