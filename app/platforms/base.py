"""Abstract base class and result container for all third-party platform adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

import httpx

from app.config import Settings
from app.schemas import PlatformResult
from app.utils.http import verify_url_public_access
from app.utils.security import redact_secrets

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishOutput:
    """Internal result returned by a concrete adapter's `_publish` implementation."""

    posted_url: str | None
    public_access_override: bool | None = None
    note: str | None = None


class PlatformAdapter(ABC):
    """Base interface that every platform integration must implement."""

    name: str = "base"
    is_ inherently_private: bool = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def missing_credentials(self) -> list[str]:
        """Return a list of required environment variable names that are unset."""

    @abstractmethod
    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        """Publish the message to the platform and return `PublishOutput`.

        Raises an exception or `RuntimeError` if publication fails.
        """

    async def verify_public_access(
        self,
        client: httpx.AsyncClient,
        publish_output: PublishOutput,
    ) -> bool:
        """Verify whether the created post is publicly readable without credentials."""
        if publish_output.public_access_override is not None:
            return publish_output.public_access_override
        if self.is_inherently_private or not publish_output.posted_url:
            return False
        return await verify_url_public_access(
            client,
            publish_output.posted_url,
            timeout_seconds=self.settings.public_verify_timeout_seconds,
        )

    async def post(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PlatformResult:
        """Execute credential check, publication, public verification, and error handling.

        Guaranteed never to raise an exception out to the caller.
        """
        missing = self.missing_credentials()
        if missing:
            err_msg = f"Missing credentials: {', '.join(missing)}"
            logger.warning("[%s] Skipping post - %s", self.name, err_msg)
            return self._failed_result(err_msg)

        try:
            logger.info("[%s] Publishing message...", self.name)
            output = await self._publish(client, message, link)
            now_utc = datetime.now(timezone.utc)
            is_public = await self.verify_public_access(client, output)

            logger.info(
                "[%s] Successfully published (url=%s, public_access=%s)",
                self.name,
                output.posted_url,
                is_public,
            )
            return PlatformResult(
                platform=self.name,
                status="success",
                posted_url=output.posted_url,
                public_access=is_public,
                date=now_utc.strftime("%Y-%m-%d"),
                time=now_utc.strftime("%H:%M:%S"),
                error=output.note,
            )
        except Exception as exc:
            safe_error = redact_secrets(str(exc), self.settings.secret_values())
            if not safe_error:
                safe_error = f"Unexpected {type(exc).__name__} during publication."
            logger.error("[%s] Publication failed: %s", self.name, safe_error)
            return self._failed_result(safe_error)

    def _failed_result(self, error_message: str) -> PlatformResult:
        """Construct a standardized failed PlatformResult."""
        return PlatformResult(
            platform=self.name,
            status="failed",
            posted_url=None,
            public_access=False,
            date=None,
            time=None,
            error=error_message,
        )

    @staticmethod
    def raise_for_response(response: httpx.Response, platform_label: str) -> None:
        """Raise a descriptive RuntimeError if the HTTP response indicates failure."""
        if 200 <= response.status_code < 300:
            return
        snippet = response.text[:300].strip() if response.text else "No response body"
        raise RuntimeError(
            f"{platform_label} API error (HTTP {response.status_code}): {snippet}"
        )