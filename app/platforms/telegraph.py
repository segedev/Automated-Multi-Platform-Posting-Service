"""Telegraph (telegra.ph) platform adapter."""

from datetime import datetime, timezone
import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


class TelegraphAdapter(PlatformAdapter):
    """Publishes a public page via the official Telegraph API (https://telegra.ph/api)."""

    name = "telegraph"
    API_URL = "https://api.telegra.ph/createPage"

    def missing_credentials(self) -> list[str]:
        if not self.settings.telegraph_access_token.strip():
            return ["TELEGRAPH_ACCESS_TOKEN"]
        return []

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        title = f"Update ({timestamp})"

        # Build Telegraph Node element with clickable link
        content_nodes = [
            {
                "tag": "p",
                "children": [
                    f"{message}\n",
                    {"tag": "a", "attrs": {"href": link}, "children": [link]},
                ],
            }
        ]

        payload = {
            "access_token": self.settings.telegraph_access_token.strip(),
            "title": title,
            "author_name": "Automated Poster",
            "content": content_nodes,
            "return_content": False,
        }

        budget = max(3.0, self.settings.platform_timeout_seconds - 4.0)
        response = await request_with_safe_retry(
            client,
            "POST",
            self.API_URL,
            json=payload,
            budget_seconds=budget,
            platform_name=self.name,
        )
        self.raise_for_response(response, "Telegraph")

        data = response.json()
        if not data.get("ok"):
            error_detail = data.get("error", "Unknown Telegraph error")
            raise RuntimeError(f"Telegraph API returned ok=false: {error_detail}")

        url = data.get("result", {}).get("url")
        if not url:
            raise RuntimeError("Telegraph response missing 'result.url'")

        return PublishOutput(posted_url=str(url))