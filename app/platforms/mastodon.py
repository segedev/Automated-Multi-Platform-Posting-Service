"""Mastodon platform adapter with Idempotency-Key protection."""

import uuid
import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


class MastodonAdapter(PlatformAdapter):
    """Publishes a public status to a Mastodon instance via POST /api/v1/statuses."""

    name = "mastodon"

    def missing_credentials(self) -> list[str]:
        missing: list[str] = []
        if not self.settings.mastodon_access_token.strip():
            missing.append("MASTODON_ACCESS_TOKEN")
        if not self.settings.mastodon_instance_url.strip():
            missing.append("MASTODON_INSTANCE_URL")
        return missing

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        base_url = self.settings.mastodon_instance_url.strip().rstrip("/")
        endpoint = f"{base_url}/api/v1/statuses"

        # Generate one Idempotency-Key per logical post operation so any retry
        # on 429/5xx is deduplicated by the Mastodon server.
        idempotency_key = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {self.settings.mastodon_access_token.strip()}",
            "Idempotency-Key": idempotency_key,
        }
        payload = {
            "status": message,
            "visibility": "public",
        }

        budget = max(3.0, self.settings.platform_timeout_seconds - 4.0)
        response = await request_with_safe_retry(
            client,
            "POST",
            endpoint,
            headers=headers,
            json=payload,
            budget_seconds=budget,
            platform_name=self.name,
        )
        self.raise_for_response(response, "Mastodon")

        data = response.json()
        post_url = data.get("url") or data.get("uri")
        if not post_url:
            raise RuntimeError("Mastodon response missing 'url'")

        return PublishOutput(posted_url=str(post_url))