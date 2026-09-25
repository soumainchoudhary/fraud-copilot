"""Fraud Investigation Copilot — FastAPI Application.

Tier-1 Enterprise platform:
1. /score — ML-based fraud risk scoring (XGBoost) + Champion/Challenger shadow + MLOps drift
2. /ask   — RAG-powered investigation assistant (ChromaDB + BM25 + Gemini)
3. /cases — Multi-tenant case repository, mule network graph, FinCEN SAR compliance
4. /ws    — Real-time live transaction event streaming
"""
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.db.database import init_db
from app.db.repository import repository
from app.graph.graph_service import get_graph_service
from app.rag.hybrid_retriever import get_bm25_index
from app.routers.ask import router as ask_router
from app.routers.cases import _load_cases
from app.routers.cases import router as cases_router
from app.routers.health import router as health_router
from app.routers.metrics import router as metrics_router
from app.routers.score import router as score_router
from app.routers.stream import router as stream_router
from app.security.auth import verify_api_key
from app.security.headers import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.security.rate_limiter import RateLimitMiddleware

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if get_settings().log_level == "DEBUG"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, get_settings().log_level.upper(), logging.INFO)
    ),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize database, load model, warm up graph, BM25, and ChromaDB."""
    settings = get_settings()
    logger.info("startup", model_path=settings.model_path, gemini_model=settings.gemini_model)

    # Initialize relational database tables & seed synthetic cases if needed
    try:
        init_db()
        seeded_count = repository.seed_if_empty()
        logger.info("relational_db_ready", seeded_cases=seeded_count)
    except Exception as e:
        logger.error("relational_db_init_failed", error=str(e))

    # Load ML model if artifact exists
    model_path = Path(settings.model_path)
    if model_path.exists():
        from app.scoring.predict import load_model
        load_model()
        logger.info("model_ready", path=str(model_path))
    else:
        logger.warning("model_not_found", path=str(model_path),
                       hint="Run 'python -m app.scoring.train' to train the model")

    # Warm up in-memory case database & entity graph
    cases = _load_cases()
    graph_svc = get_graph_service()
    if graph_svc.graph.number_of_nodes() == 0 and cases:
        graph_svc.build_graph(cases)
    logger.info("cases_and_graph_prewarmed", count=len(cases), graph_nodes=graph_svc.graph.number_of_nodes())

    # Prewarm BM25 sparse index
    bm25 = get_bm25_index()
    if bm25.doc_count == 0 and cases:
        bm25.fit(cases)

    # Initialize ChromaDB collection if data exists
    chroma_dir = Path(settings.chroma_persist_dir)
    if chroma_dir.exists():
        logger.info("chroma_ready", path=str(chroma_dir))
    else:
        logger.warning(
            "chroma_not_found",
            path=str(chroma_dir),
            hint="Run 'python -m app.rag.ingest' to index case records",
        )

    yield

    logger.info("shutdown")


# Create FastAPI app with native Pydantic v2 fast JSON serialization
app = FastAPI(
    title="Fraud Investigation Copilot",
    description=(
        "Tier-1 FinTech ML-based fraud scoring engine and RAG-powered investigation assistant. "
        "Score transactions for fraud risk, inspect mule network rings, generate FinCEN SARs, "
        "and track real-time WebSocket live transaction streams."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    correlation_id = str(uuid.uuid4())
    logger.error(
        "unhandled_server_exception",
        correlation_id=correlation_id,
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error. Contact security team with correlation ID.",
            "correlation_id": correlation_id,
        },
    )


# Middlewares (Executed in reverse order: Headers -> RateLimiter -> CORS -> GZip -> Routers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# Health, WebSocket stream, and Prometheus metrics endpoints are public for monitoring & dashboard UI
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(stream_router)

# Core business endpoints protected by API Key authentication
app.include_router(score_router, dependencies=[Depends(verify_api_key)])
app.include_router(ask_router, dependencies=[Depends(verify_api_key)])
app.include_router(cases_router, dependencies=[Depends(verify_api_key)])

# Mount static files and serve dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def serve_dashboard():
        """Serve the interactive Fraud Copilot investigator dashboard."""
        return FileResponse(static_dir / "index.html")
