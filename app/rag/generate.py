"""RAG answer generation using Google Gemini API.

Constructs a grounded prompt from retrieved case records and uses
Gemini 3.8 Flash to generate cited answers.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from app.config import get_settings
from app.security.sanitizer import sanitize_context_chunk, sanitize_prompt_text

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are a fraud investigation assistant. Your job is to answer
questions from investigators about flagged fraud cases.

RULES:
1. Answer ONLY from the provided case records in <context> tags. Do not use external knowledge.
2. If the retrieved cases do not contain enough information to answer the question,
   say "Based on the provided case records, there is insufficient information to answer
   this question." — do not guess or extrapolate.
3. Always cite the case_id for every claim using format [Case: CASE-ID].
4. Be concise and factual. This is for investigation, not conversation.
5. If cases contradict each other, document both sides and cite each Case ID.
6. If asked about accounts, UPI IDs, or risk scores, reference specific values from cases.
"""


def _format_case_context(cases: list[dict[str, Any]]) -> str:
    """Format retrieved cases as XML-tagged context for clean separation."""
    parts = ["<context>"]
    for c in cases:
        risk = c.get("metadata", {}).get("risk_score", c.get("score", "N/A"))
        clean_doc = sanitize_context_chunk(str(c.get("document", "")))
        clean_id = sanitize_prompt_text(str(c.get("case_id", "")))
        parts.append(
            f'  <case id="{clean_id}" risk="{risk}">'
            f'\n    {clean_doc}\n'
            f'  </case>'
        )
    parts.append("</context>")
    return "\n".join(parts)


_gemini_client: Any | None = None


def _get_gemini_client():
    """Lazy-initialize and cache the Gemini client singleton to reuse HTTP/SSL connection pools."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    settings = get_settings()
    # Set API key in environment for the SDK
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    from google import genai
    _gemini_client = genai.Client()
    return _gemini_client


def generate_answer(
    query: str,
    retrieved_cases: list[dict[str, Any]],
) -> str:
    """Generate a grounded answer with case citations.

    Args:
        query: The investigator's natural language question.
        retrieved_cases: List of retrieved case dicts from the retriever.

    Returns:
        Generated answer text with [Case: CASE-ID] citations.
    """
    settings = get_settings()

    if not retrieved_cases:
        return (
            "Based on the provided case records, there is insufficient "
            "information to answer this question. No relevant cases were found."
        )

    # Sanitize user input to prevent prompt injection and delimiter escape
    safe_query = sanitize_prompt_text(query, max_length=settings.max_query_length)
    context = _format_case_context(retrieved_cases)

    prompt = f"""{context}

<question>
{safe_query}
</question>

Answer the question using ONLY the cases in <context>. Cite every claim with [Case: {{case_id}}]."""

    try:
        client = _get_gemini_client()
        interaction = client.interactions.create(
            model=settings.gemini_model,
            system_instruction=SYSTEM_PROMPT,
            input=prompt,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 1024,
                "thinking_level": "low",
            },
        )
        answer = interaction.output_text
        logger.info(
            "answer_generated",
            query=query[:100],
            num_cases=len(retrieved_cases),
            answer_length=len(answer) if answer else 0,
        )
        return answer or "Failed to generate an answer. Please try again."

    except Exception as e:
        logger.error("generation_failed", error=str(e), query=query[:100])
        # Fallback: return a formatted summary without LLM
        fallback_parts = ["[LLM unavailable — returning raw retrieved cases]\n"]
        for c in retrieved_cases:
            fallback_parts.append(
                f"**[Case: {c['case_id']}]** (score: {c['score']})\n"
                f"{c['document'][:300]}...\n"
            )
        return "\n".join(fallback_parts)
