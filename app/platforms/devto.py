"""Dev.to (Forem API v1) platform adapter."""

from datetime import datetime, timezone
import re
import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


class DevToAdapter(PlatformAdapter):
    """Publishes an article to Dev.to using the official Forem v1 API."""

    name = "devto"
    API_URL = "https://dev.to/api/articles"

    def missing_credentials(self) -> list[str]:
        if not self.settings.devto_api_key.strip():
            return ["DEVTO_API_KEY"]
        return []

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        # Strip the raw URL from the title snippet and append a UTC timestamp suffix
        # so repeated test runs never hit Forem's "title has already been taken" error.
        text_without_url = re.sub(r"https?://[^\s]+", "", message).strip()
        prefix = (text_without_url[:45].strip() or "Platform Update")
        ts_suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:19]
        title = f"{prefix} [{ts_suffix}]"

        headers = {
            "api-key": self.settings.devto_api_key.strip(),
            "Accept": "application/vnd.forem.api-v1+json",
            "Content-Type": "application/json",
        }
        payload = {
            "article": {
                "title": title,
                "body_markdown": f"{message}\n\n[Visit Link]({link})",
                "published": True,
                "tags": ["news", "updates"],
            }
        }

        budget = max(3.0, self.settings.platform_timeout_seconds - 4.0)
        response = await request_with_safe_retry(
            client,
            "POST",
            self.API_URL,
            headers=headers,
            json=payload,
            budget_seconds=budget,
            platform_name=self.name,
        )
        self.raise_for_response(response, "Dev.to")

        data = response.json()
        url = data.get("url")
        if not url:
            raise RuntimeError("Dev.to response missing 'url'")

        return PublishOutput(posted_url=str(url))