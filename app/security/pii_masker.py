"""PII Redaction and Sanitization utility for FinTech enterprise privacy compliance."""
from __future__ import annotations

import re
from typing import Any

# Regex patterns for sensitive identifiers
_CARD_PAN_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}(\d{4})\b")
_PHONE_PATTERN = re.compile(r"(\+?\d{1,3}[-\s]?)?(\d{2,4})[-\s]?(\d{3,5})[-\s]?(\d{4})\b")
_EMAIL_PATTERN = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_ACCOUNT_NUM_PATTERN = re.compile(r"\b(\d{4})\d{4,8}(\d{4})\b")
_SSN_PATTERN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?(\d{4})\b")


def mask_card_pan(text: str) -> str:
    """Mask primary account number preserving first 4 and last 4 digits."""
    return _CARD_PAN_PATTERN.sub(r"XXXX-XXXX-XXXX-\1", text)


def mask_phone(text: str) -> str:
    """Mask phone numbers preserving prefix and last 4 digits."""
    def _repl(match: re.Match) -> str:
        prefix = match.group(1) or ""
        last4 = match.group(4)
        return f"{prefix}XXXXX-{last4}"
    return _PHONE_PATTERN.sub(_repl, text)


def mask_email(text: str) -> str:
    """Mask email addresses (e.g., j***n@domain.com)."""
    return _EMAIL_PATTERN.sub(r"\1***@\2", text)


def mask_account_number(text: str) -> str:
    """Mask financial bank accounts preserving first 4 and last 4 digits."""
    return _ACCOUNT_NUM_PATTERN.sub(r"\1XXXX\2", text)


def mask_pii(text: str) -> str:
    """Redact all sensitive PII tokens within natural language text."""
    if not text or not isinstance(text, str):
        return text

    masked = mask_card_pan(text)
    masked = _SSN_PATTERN.sub(r"XXX-XX-\1", masked)
    masked = mask_account_number(masked)
    masked = mask_email(masked)
    masked = mask_phone(masked)
    return masked


def mask_case_dict(case_data: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of a case record with PII redacted for non-privileged viewers."""
    if not isinstance(case_data, dict):
        return case_data

    sanitized = dict(case_data)

    if "phone" in sanitized and sanitized["phone"]:
        sanitized["phone"] = mask_phone(str(sanitized["phone"]))

    if "email" in sanitized and sanitized["email"]:
        sanitized["email"] = mask_email(str(sanitized["email"]))

    if "account_number" in sanitized and sanitized["account_number"]:
        sanitized["account_number"] = mask_account_number(str(sanitized["account_number"]))

    if "complaint_text" in sanitized and sanitized["complaint_text"]:
        sanitized["complaint_text"] = mask_pii(str(sanitized["complaint_text"]))

    if "investigator_notes" in sanitized and sanitized["investigator_notes"]:
        sanitized["investigator_notes"] = mask_pii(str(sanitized["investigator_notes"]))

    return sanitized
