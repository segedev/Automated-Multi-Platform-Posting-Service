"""Pydantic v2 request and response schemas with strict message and URL validation."""

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

MAX_MESSAGE_LENGTH = 200

# Matches explicit scheme tokens (e.g. https://..., ftp://..., javascript:...)
_SCHEME_TOKEN_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*:(?://)?[^\s]+)")
# Matches bare www. domains or obvious bare domains with common TLDs not preceded by :// or @
_BARE_LINK_RE = re.compile(
    r"(?<![/@\w.])(?:www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s]*|[a-zA-Z0-9\-]+\.(?:com|org|net|io|co|app|dev|ai|me|xyz|info|biz|edu|gov)(?:/[^\s]*)?)\b",
    re.IGNORECASE,
)
_TRAILING_PUNCTUATION = ".,!?;:)]}'\""
_VALID_HOST_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$|^localhost$"
)


def _clean_token(token: str) -> str:
    """Strip sentence-ending punctuation from a candidate URL token."""
    return token.rstrip(_TRAILING_PUNCTUATION)


def _is_valid_http_url(url_str: str) -> tuple[bool, str]:
    """Validate that a URL has an http/https scheme and a valid network host."""
    try:
        parsed = urlparse(url_str)
    except ValueError:
        return False, f"Malformed URL: '{url_str}'."

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return (
            False,
            f"Invalid URL scheme '{parsed.scheme}:' in '{url_str}'. Only 'http://' and 'https://' are allowed.",
        )

    if not parsed.netloc or parsed.username or parsed.password:
        return False, f"URL '{url_str}' must include a valid host without embedded credentials."

    host = parsed.hostname or ""
    if not _VALID_HOST_RE.match(host):
        return False, f"URL '{url_str}' has an invalid hostname '{host}'."

    return True, ""


def extract_and_validate_cta_link(message: str) -> str:
    """Validate message constraints and return the single validated CTA URL.

    Rules enforced:
    1. Message must not be empty or whitespace-only.
    2. Total message length (including the URL) must be <= 200 characters.
    3. Exactly ONE CTA link must exist in the message.
    4. Disallowed schemes (javascript:, ftp:, etc.) or bare links without http(s):// are rejected.
    """
    if not message or not message.strip():
        raise ValueError("Message must not be empty or whitespace only.")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(
            f"Message length ({len(message)} characters) exceeds the maximum allowed "
            f"limit of {MAX_MESSAGE_LENGTH} characters (including the URL)."
        )

    # Scan whitespace-delimited tokens to catch all URL-like patterns accurately
    scheme_candidates: list[str] = []
    bare_candidates: list[str] = []

    for raw_token in message.split():
        token = _clean_token(raw_token)
        if not token:
            continue
        if _SCHEME_TOKEN_RE.match(token):
            scheme_candidates.append(token)
        elif _BARE_LINK_RE.fullmatch(token):
            bare_candidates.append(token)

    total_links = len(scheme_candidates) + len(bare_candidates)

    if total_links == 0:
        raise ValueError(
            "Message must contain exactly one valid http:// or https:// CTA link (found 0)."
        )

    if total_links > 1:
        all_found = scheme_candidates + bare_candidates
        raise ValueError(
            f"Message must contain exactly one CTA link, but found {total_links}: {all_found}."
        )

    if bare_candidates:
        bad_link = bare_candidates[0]
        raise ValueError(
            f"Invalid URL '{bad_link}': missing explicit 'http://' or 'https://' scheme."
        )

    candidate_url = scheme_candidates[0]
    is_valid, error_reason = _is_valid_http_url(candidate_url)
    if not is_valid:
        raise ValueError(error_reason)

    return candidate_url


class PostingRequest(BaseModel):
    """Incoming payload for POST /posting."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        ...,
        description="Short announcement message (<= 200 chars total) containing exactly one HTTP/HTTPS link.",
        examples=["Check out our latest business platform https://example.com"],
    )
    _extracted_link: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def _validate_message_and_link(self) -> "PostingRequest":
        """Validate message rules and cache the extracted CTA URL."""
        self._extracted_link = extract_and_validate_cta_link(self.message)
        return self

    @property
    def link(self) -> str:
        """Return the validated CTA link extracted from the message."""
        return self._extracted_link


class PlatformResult(BaseModel):
    """Per-platform publication result."""

    platform: str = Field(..., description="Platform identifier.")
    status: Literal["success", "failed"] = Field(..., description="Publication outcome.")
    posted_url: str | None = Field(
        default=None,
        description="Direct URL to the published post, or null if failed or unavailable.",
    )
    public_access: bool = Field(
        ...,
        description="Whether the post was verified to be publicly accessible without authentication.",
    )
    date: str | None = Field(
        default=None,
        description="UTC date of publication (YYYY-MM-DD), or null if failed.",
    )
    time: str | None = Field(
        default=None,
        description="UTC time of publication (HH:MM:SS), or null if failed.",
    )
    error: str | None = Field(
        default=None,
        description="Redacted error reason if status is 'failed', or informational note.",
    )


class PostingResponse(BaseModel):
    """Top-level response returned by POST /posting."""

    success: bool = Field(
        ...,
        description="True if at least one platform succeeded, False if all platforms failed.",
    )
    results: list[PlatformResult] = Field(
        ...,
        description="Ordered per-platform publication results.",
    )