"""Service orchestrating concurrent publication across all registered platforms."""

import asyncio
import logging
from typing import Sequence

import httpx

from app.config import Settings
from app.platforms.base import PlatformAdapter
from app.schemas import PlatformResult, PostingResponse
from app.utils.security import redact_secrets

logger = logging.getLogger(__name__)


class PostingService:
    """Runs all registered platform adapters concurrently and aggregates results."""

    def __init__(
        self,
        adapters: Sequence[PlatformAdapter],
        settings: Settings,
    ) -> None:
        self.adapters = list(adapters)
        self.settings = settings

    async def publish_all(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PostingResponse:
        """Publish `message` and `link` to all adapters concurrently with individual timeouts."""
        tasks = [
            self._run_adapter_with_timeout(adapter, client, message, link)
            for adapter in self.adapters
        ]
        raw_outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[PlatformResult] = []
        for adapter, outcome in zip(self.adapters, raw_outcomes, strict=True):
            if isinstance(outcome, PlatformResult):
                results.append(outcome)
            else:
                # Defensive fallback if an unexpected BaseException escaped
                safe_err = redact_secrets(
                    f"Unhandled exception ({type(outcome).__name__}): {outcome}",
                    self.settings.secret_values(),
                )
                logger.error("[%s] %s", adapter.name, safe_err)
                results.append(
                    PlatformResult(
                        platform=adapter.name,
                        status="failed",
                        posted_url=None,
                        public_access=False,
                        date=None,
                        time=None,
                        error=safe_err,
                    )
                )

        overall_success = any(r.status == "success" for r in results)
        return PostingResponse(success=overall_success, results=results)

    async def _run_adapter_with_timeout(
        self,
        adapter: PlatformAdapter,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PlatformResult:
        """Wrap a single adapter call in `asyncio.wait_for` to enforce hard timeout."""
        timeout_sec = self.settings.platform_timeout_seconds
        try:
            return await asyncio.wait_for(
                adapter.post(client, message, link),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            err_msg = f"Timed out after {timeout_sec:.1f}s"
            logger.error("[%s] %s", adapter.name, err_msg)
            return PlatformResult(
                platform=adapter.name,
                status="failed",
                posted_url=None,
                public_access=False,
                date=None,
                time=None,
                error=err_msg,
            )
        except Exception as exc:
            safe_err = redact_secrets(str(exc), self.settings.secret_values())
            logger.error("[%s] Unexpected error: %s", adapter.name, safe_err)
            return PlatformResult(
                platform=adapter.name,
                status="failed",
                posted_url=None,
                public_access=False,
                date=None,
                time=None,
                error=safe_err or f"Unexpected {type(exc).__name__}",
            )