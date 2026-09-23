"""Input sanitization and anti-prompt injection defenses for LLM and RAG queries."""
import re

# Regex for non-printable ASCII control characters (excluding newline \n, return \r, tab \t)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Common prompt injection / jailbreak / exfiltration patterns
JAILBREAK_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)\s+instructions?", re.IGNORECASE),
    re.compile(r"repeat\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|words?)", re.IGNORECASE),
    re.compile(r"(output|show|reveal|display|print)\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?|directives?)", re.IGNORECASE),
    re.compile(r"what\s+are\s+(your\s+)?(system\s+)?(instructions?|prompts?|rules?|directives?)", re.IGNORECASE),
    re.compile(r"(you\s+are\s+now\s+|act\s+as\s+)(a|an|unrestricted|unfiltered|free|evil|dan)", re.IGNORECASE),
    re.compile(r"(DAN|jailbreak|developer)\s+mode", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
]


def sanitize_prompt_text(text: str, max_length: int = 1000) -> str:
    """Sanitize user query before passing to LLM prompts.

    1. Truncates text to max_length.
    2. Strips non-printable ASCII control characters.
    3. Neutralizes XML/HTML tags to prevent prompt injection and context escaping.
    4. Disarms known jailbreak and instruction-override phrases.

    Args:
        text: Raw user input query.
        max_length: Maximum allowed characters.

    Returns:
        Sanitized safe string.
    """
    if not text:
        return ""

    # Truncate
    cleaned = text[:max_length].strip()

    # Remove non-printable control characters
    cleaned = CONTROL_CHAR_RE.sub("", cleaned)

    # Disarm XML delimiters to prevent prompt boundary escape (<question>, </context>, etc.)
    cleaned = cleaned.replace("<", "[").replace(">", "]")

    # Neutralize jailbreak overrides
    for pattern in JAILBREAK_PATTERNS:
        cleaned = pattern.sub("[FILTERED_OVERRIDE_ATTEMPT]", cleaned)

    return cleaned


def sanitize_context_chunk(text: str) -> str:
    """Sanitize retrieved database chunks to prevent indirect prompt injection."""
    if not text:
        return ""
    cleaned = CONTROL_CHAR_RE.sub("", text)
    # Neutralize XML tags inside context chunks to prevent escaping XML delimiters
    cleaned = cleaned.replace("<", "[").replace(">", "]")
    return cleaned
