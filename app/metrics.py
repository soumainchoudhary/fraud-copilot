"""Lightweight, thread-safe Prometheus metrics registry for Fraud Copilot."""
import threading


class MetricsRegistry:
    """Thread-safe Prometheus metrics accumulator."""

    def __init__(self):
        self._lock = threading.Lock()
        self._scored_clean = 0
        self._scored_flagged = 0
        self._score_latency_sum = 0.0
        self._score_latency_count = 0
        self._rag_queries = 0
        self._rate_limit_blocks = 0
        self._case_updates = 0

    def inc_scored(self, flagged: bool, latency_seconds: float = 0.0) -> None:
        """Increment transaction scoring counters."""
        with self._lock:
            if flagged:
                self._scored_flagged += 1
            else:
                self._scored_clean += 1
            self._score_latency_sum += max(0.0, latency_seconds)
            self._score_latency_count += 1

    def inc_rag_query(self) -> None:
        """Increment RAG investigation queries counter."""
        with self._lock:
            self._rag_queries += 1

    def inc_rate_limit_block(self) -> None:
        """Increment rate limit rejections counter."""
        with self._lock:
            self._rate_limit_blocks += 1

    def inc_case_update(self) -> None:
        """Increment case updates counter."""
        with self._lock:
            self._case_updates += 1

    def export_text(self) -> str:
        """Render metrics in Prometheus text exposition format (version 0.0.4)."""
        with self._lock:
            lines = [
                "# HELP fraud_transactions_scored_total Total number of transactions scored by model",
                "# TYPE fraud_transactions_scored_total counter",
                f'fraud_transactions_scored_total{{status="flagged"}} {self._scored_flagged}',
                f'fraud_transactions_scored_total{{status="clean"}} {self._scored_clean}',
                "",
                "# HELP fraud_scoring_latency_seconds_sum Total cumulative scoring latency in seconds",
                "# TYPE fraud_scoring_latency_seconds_sum counter",
                f"fraud_scoring_latency_seconds_sum {round(self._score_latency_sum, 6)}",
                "",
                "# HELP fraud_scoring_latency_seconds_count Total count of scoring evaluations",
                "# TYPE fraud_scoring_latency_seconds_count counter",
                f"fraud_scoring_latency_seconds_count {self._score_latency_count}",
                "",
                "# HELP fraud_rag_queries_total Total natural-language RAG investigation queries",
                "# TYPE fraud_rag_queries_total counter",
                f"fraud_rag_queries_total {self._rag_queries}",
                "",
                "# HELP fraud_rate_limit_rejections_total Total requests rejected by sliding window rate limiter (HTTP 429)",
                "# TYPE fraud_rate_limit_rejections_total counter",
                f"fraud_rate_limit_rejections_total {self._rate_limit_blocks}",
                "",
                "# HELP fraud_cases_updated_total Total forensic cases updated or resolved",
                "# TYPE fraud_cases_updated_total counter",
                f"fraud_cases_updated_total {self._case_updates}",
                "",
            ]
            return "\n".join(lines)


# Singleton metrics instance
metrics = MetricsRegistry()
