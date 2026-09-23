"""RAG investigation assistant endpoint."""
import time
import uuid

import structlog
from fastapi import APIRouter

from app.metrics import metrics
from app.models.schemas import AskRequest, AskResponse, Source
from app.rag.generate import generate_answer
from app.rag.retriever import retrieve

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["rag"])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Ask a natural-language question about flagged fraud cases.

    Retrieves the most relevant case records from the vector store,
    then generates a grounded answer with case citations.
    """
    request_id = str(uuid.uuid4())
    start_time = time.perf_counter()
    metrics.inc_rag_query()

    logger.info(
        "ask_request",
        request_id=request_id,
        query=request.query[:200],
        top_k=request.top_k,
    )

    # 1. Retrieve top-k cases
    retrieved = retrieve(query=request.query, top_k=request.top_k)

    # 2. Generate answer with citations
    answer = generate_answer(query=request.query, retrieved_cases=retrieved)

    # 3. Build Source objects
    sources = [
        Source(
            case_id=r["case_id"],
            snippet=r["document"][:500],  # Truncate for response
            score=r["score"],
        )
        for r in retrieved
    ]

    latency_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "ask_response",
        request_id=request_id,
        num_sources=len(sources),
        answer_length=len(answer),
        latency_ms=round(latency_ms, 2),
    )

    return AskResponse(answer=answer, sources=sources)
