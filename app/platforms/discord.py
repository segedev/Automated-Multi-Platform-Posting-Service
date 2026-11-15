"""Discord Webhook platform adapter."""

import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


class DiscordWebhookAdapter(PlatformAdapter):
    """Publishes a message via a Discord Webhook (`?wait=true`).

    Discord channels require authenticated server membership, so `public_access`
    is always `False`. If `guild_id` is available in the webhook response (or via
    `DISCORD_GUILD_ID`), constructs `https://discord.com/channels/<guild_id>/<channel_id>/<id>`;
    otherwise returns `posted_url=None` with an explanatory note rather than
    fabricating a `@me` DM URL.
    """

    name = "discord"
    is_inherently_private = True

    def missing_credentials(self) -> list[str]:
        if not self.settings.discord_webhook_url.strip():
            return ["DISCORD_WEBHOOK_URL"]
        return []

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        webhook_url = self.settings.discord_webhook_url.strip()
        budget = max(3.0, self.settings.platform_timeout_seconds - 4.0)

        response = await request_with_safe_retry(
            client,
            "POST",
            webhook_url,
            params={"wait": "true"},
            json={"content": message},
            budget_seconds=budget,
            platform_name=self.name,
        )
        self.raise_for_response(response, "Discord Webhook")

        data = response.json()
        message_id = data.get("id")
        channel_id = data.get("channel_id")
        guild_id = data.get("guild_id") or self.settings.discord_guild_id.strip() or None

        if not message_id or not channel_id:
            raise RuntimeError("Discord webhook response missing 'id' or 'channel_id'")

        if guild_id:
            jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            return PublishOutput(
                posted_url=jump_url,
                public_access_override=False,
            )

        return PublishOutput(
            posted_url=None,
            public_access_override=False,
            note=(
                f"Webhook message published (channel_id={channel_id}, message_id={message_id}); "
                "guild_id not returned by Discord webhook payload, so no jump URL was constructed."
            ),
        )