"""Vector search over ChromaDB fraud case collection."""
from __future__ import annotations

from typing import Any

import chromadb
import structlog
from chromadb.utils import embedding_functions

from app.config import get_settings

logger = structlog.get_logger(__name__)

_collection: chromadb.Collection | None = None
_retrieval_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
_MAX_CACHE_SIZE = 256


def _get_embedding_function() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """Create the sentence-transformer embedding function."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2",
        device="cpu",
        normalize_embeddings=True,
    )


def get_collection() -> chromadb.Collection:
    """Get the fraud_cases collection, creating a persistent client."""
    global _collection
    if _collection is not None:
        return _collection

    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    _collection = client.get_or_create_collection(
        name="fraud_cases",
        embedding_function=_get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def clear_retrieval_cache() -> None:
    """Clear the in-memory query retrieval cache."""
    global _retrieval_cache
    _retrieval_cache.clear()


def retrieve(
    query: str,
    top_k: int = 5,
    collection: chromadb.Collection | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the top-k most relevant case records for a query with in-memory caching.

    Args:
        query: Natural language investigator question.
        top_k: Number of results to return.
        collection: Optional collection override (for testing).

    Returns:
        List of dicts with keys: case_id, document, score, metadata
    """
    global _retrieval_cache

    # If using default collection, check in-memory LRU cache
    cache_key = (query.strip().lower(), top_k)
    if collection is None and cache_key in _retrieval_cache:
        return _retrieval_cache[cache_key]

    coll = collection or get_collection()

    results = coll.query(
        query_texts=[query],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    if not results["documents"] or not results["documents"][0]:
        logger.info("retrieval_empty", query=query)
        return []

    retrieved = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        retrieved.append({
            "case_id": meta["case_id"],
            "document": doc,
            "score": round(1 - dist, 4),  # cosine similarity = 1 - cosine distance
            "metadata": meta,
        })

    # Cache result if using default collection
    if collection is None:
        if len(_retrieval_cache) >= _MAX_CACHE_SIZE:
            _retrieval_cache.pop(next(iter(_retrieval_cache)))
        _retrieval_cache[cache_key] = retrieved

    logger.info(
        "cases_retrieved",
        query=query[:100],
        top_k=top_k,
        returned=len(retrieved),
        top_score=retrieved[0]["score"] if retrieved else None,
    )
    return retrieved
