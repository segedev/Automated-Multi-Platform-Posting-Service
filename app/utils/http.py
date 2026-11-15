"""HTTP retry helper for safe idempotent/transient retries and public URL verification."""

import asyncio
import logging
import time
from typing import Any, Mapping

import httpx

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})
MAX_RETRIES = 2
BASE_BACKOFF_SECONDS = 0.5


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Extract wait duration from HTTP Retry-After header or Telegram JSON body."""
    header_val = response.headers.get("Retry-After")
    if header_val:
        try:
            return max(0.0, float(header_val))
        except ValueError:
            pass

    # Check Telegram-style {"parameters": {"retry_after": <int>}}
    try:
        data = response.json()
        if isinstance(data, dict):
            params = data.get("parameters")
            if isinstance(params, dict) and "retry_after" in params:
                return max(0.0, float(params["retry_after"]))
    except Exception:
        pass

    return None


async def request_with_safe_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    params: Mapping[str, str] | None = None,
    budget_seconds: float = 12.0,
    max_retries: int = MAX_RETRIES,
    platform_name: str = "Platform",
) -> httpx.Response:
    """Execute an HTTP request with bounded retries for safe transient errors only.

    Duplicate-post prevention rules:
    - NEVER retry httpx.ReadTimeout or httpx.WriteTimeout on POST requests because
      the server may have already received and published the post.
    - ONLY retry pre-transmission connection errors (ConnectError, ConnectTimeout, PoolTimeout)
      and explicit HTTP 429, 502, 503, 504 responses.
    - Never retry 4xx authentication or validation errors (400, 401, 403, 404, 422).
    - Ensure sleep + subsequent attempt stays within `budget_seconds`.
    """
    start_monotonic = time.monotonic()
    attempt = 0

    while True:
        elapsed = time.monotonic() - start_monotonic
        remaining = budget_seconds - elapsed
        if remaining <= 0.2:
            raise httpx.TimeoutException(
                f"{platform_name} exhausted retry time budget ({budget_seconds:.1f}s)."
            )

        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
                timeout=httpx.Timeout(
                    connect=min(5.0, remaining),
                    read=remaining,
                    write=min(5.0, remaining),
                    pool=min(5.0, remaining),
                ),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            if attempt >= max_retries:
                raise
            delay = min(BASE_BACKOFF_SECONDS * (2**attempt), remaining - 0.2)
            if delay <= 0:
                raise
            logger.warning(
                "[%s] Pre-request connection error (%s). Retrying in %.2fs (attempt %d/%d)",
                platform_name,
                type(exc).__name__,
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue
        except httpx.TimeoutException:
            # ReadTimeout / WriteTimeout: do NOT retry POSTs to prevent duplicate posts
            raise

        if response.status_code in TRANSIENT_STATUS_CODES and attempt < max_retries:
            retry_after = _parse_retry_after(response)
            backoff = BASE_BACKOFF_SECONDS * (2**attempt)
            delay = retry_after if retry_after is not None else backoff

            elapsed = time.monotonic() - start_monotonic
            remaining = budget_seconds - elapsed
            if delay + 0.3 >= remaining:
                # Retry wait would exceed our per-platform timeout budget; return immediately
                return response

            logger.warning(
                "[%s] Transient HTTP %d received. Retrying in %.2fs (attempt %d/%d)",
                platform_name,
                response.status_code,
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue

        return response


async def verify_url_public_access(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    """Verify whether a URL is publicly reachable via unauthenticated HEAD/GET request."""
    if not url:
        return False

    try:
        head_resp = await client.head(
            url,
            follow_redirects=True,
            timeout=timeout_seconds,
        )
        if 200 <= head_resp.status_code < 300:
            return True
        # Some servers reject HEAD with 405/403 but allow GET
        if head_resp.status_code in (403, 405, 501):
            get_resp = await client.get(
                url,
                follow_redirects=True,
                timeout=timeout_seconds,
            )
            return 200 <= get_resp.status_code < 300
        return False
    except httpx.HTTPError:
        return False