"""Sliding-window rate limiter middleware with distributed Redis and in-memory fallback."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from typing import Callable, Optional

import structlog
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

logger = structlog.get_logger(__name__)


class SlidingWindowRateLimiter:
    """Resilient sliding window rate limiter supporting Redis sorted sets with memory fallback."""

    def __init__(self, window_seconds: int = 60, redis_url: Optional[str] = None):
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
        self.redis_client = None

        target_url = redis_url or os.getenv("REDIS_URL") or get_settings().redis_url
        if target_url:
            try:
                import importlib
                redis_mod = importlib.import_module("redis")
                self.redis_client = redis_mod.Redis.from_url(target_url, decode_responses=True)
                self.redis_client.ping()
                logger.info("redis_rate_limiter_connected", url=target_url)
            except Exception as e:
                logger.warning("redis_rate_limiter_unavailable_using_memory", error=str(e))
                self.redis_client = None

    def is_allowed(self, client_key: str, max_requests: int) -> tuple[bool, int]:
        """Check if client request is within threshold.

        Returns:
            (allowed: bool, remaining: int)
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # 1. Distributed Redis Sorted Set Path
        if self.redis_client is not None:
            try:
                rk = f"ratelimit:{client_key}"
                pipe = self.redis_client.pipeline()
                pipe.zremrangebyscore(rk, 0, cutoff)
                pipe.zcard(rk)
                pipe.expire(rk, self.window_seconds + 5)
                _, current_count, _ = pipe.execute()

                if current_count >= max_requests:
                    return False, 0

                member = f"{now}:{time.perf_counter_ns()}"
                add_pipe = self.redis_client.pipeline()
                add_pipe.zadd(rk, {member: now})
                add_pipe.expire(rk, self.window_seconds + 5)
                add_pipe.execute()

                remaining = max_requests - (current_count + 1)
                return True, max(0, remaining)
            except Exception as e:
                logger.debug("redis_rate_limiter_fallback_to_memory", error=str(e))

        # 2. Thread-safe In-Memory Fallback Path
        with self.lock:
            timestamps = self.requests[client_key]
            pruned = [t for t in timestamps if t > cutoff]
            self.requests[client_key] = pruned

            if len(pruned) >= max_requests:
                return False, 0

            self.requests[client_key].append(now)
            remaining = max_requests - len(self.requests[client_key])
            return True, remaining

    def cleanup(self) -> None:
        """Periodic prune to prevent memory growth in in-memory storage."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self.lock:
            stale_keys = [k for k, v in self.requests.items() if not v or v[-1] <= cutoff]
            for k in stale_keys:
                del self.requests[k]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI Middleware enforcing client rate limits."""

    def __init__(self, app, window_seconds: int = 60):
        super().__init__(app)
        self.limiter = SlidingWindowRateLimiter(window_seconds=window_seconds)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Exempt static assets, health check, websockets, and prometheus metrics from rate limits
        path = request.url.path
        if (
            path.startswith("/static")
            or path == "/health"
            or path == "/metrics"
            or path == "/"
            or path.startswith("/ws")
        ):
            return await call_next(request)

        settings = get_settings()

        # Extract client IP (respecting proxy headers)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        # Apply dedicated limit for LLM endpoint vs general API
        if path.startswith("/ask"):
            limit = settings.ask_rate_limit_per_minute
            key = f"ask:{client_ip}"
        else:
            limit = settings.rate_limit_per_minute
            key = f"general:{client_ip}"

        allowed, remaining = self.limiter.is_allowed(key, limit)
        if not allowed:
            logger.warning("rate_limit_exceeded", client_ip=client_ip, path=path, limit=limit)
            try:
                from app.metrics import metrics
                metrics.inc_rate_limit_block()
            except Exception:
                pass
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"Rate limit exceeded. Maximum {limit} requests per minute allowed on this endpoint."
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        return response
