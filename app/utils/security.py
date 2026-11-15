"""Redaction utilities to prevent credentials from leaking into logs or API responses."""

import re
from typing import Iterable

# Patterns that commonly embed credentials in URLs or headers
_WEBHOOK_PATTERN = re.compile(
    r"(https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/)([A-Za-z0-9_\-]+)"
)
_TELEGRAM_BOT_URL_PATTERN = re.compile(
    r"(https?://api\.telegram\.org/bot)([0-9]+:[A-Za-z0-9_\-]+)"
)
_BEARER_PATTERN = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE)


def redact_secrets(text: str, known_secrets: Iterable[str] = ()) -> str:
    """Redact known secret strings and URL-embedded tokens from a message."""
    if not text:
        return text

    redacted = text
    for secret in known_secrets:
        if secret and secret in redacted:
            redacted = redacted.replace(secret, "[REDACTED]")

    redacted = _WEBHOOK_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = _TELEGRAM_BOT_URL_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = _BEARER_PATTERN.sub(r"\1[REDACTED]", redacted)
    return redacted