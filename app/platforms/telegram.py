"""Telegram Bot API platform adapter."""

import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


class TelegramAdapter(PlatformAdapter):
    """Publishes a message to a Telegram channel via the official Bot API."""

    name = "telegram"

    def missing_credentials(self) -> list[str]:
        missing: list[str] = []
        if not self.settings.telegram_bot_token.strip():
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.settings.telegram_chat_id.strip():
            missing.append("TELEGRAM_CHAT_ID")
        return missing

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        token = self.settings.telegram_bot_token.strip()
        chat_id = self.settings.telegram_chat_id.strip()
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": False,
        }

        budget = max(3.0, self.settings.platform_timeout_seconds - 4.0)
        response = await request_with_safe_retry(
            client,
            "POST",
            endpoint,
            json=payload,
            budget_seconds=budget,
            platform_name=self.name,
        )
        self.raise_for_response(response, "Telegram")

        data = response.json()
        if not data.get("ok"):
            desc = data.get("description", "Unknown Telegram error")
            raise RuntimeError(f"Telegram API error: {desc}")

        result = data.get("result", {})
        message_id = result.get("message_id")
        chat_obj = result.get("chat", {})
        username = chat_obj.get("username") or (
            chat_id.lstrip("@") if chat_id.startswith("@") else None
        )

        if not username or message_id is None:
            return PublishOutput(
                posted_url=None,
                public_access_override=False,
                note="Message sent to private chat without a public @username URL.",
            )

        posted_url = f"https://t.me/{username}/{message_id}"
        return PublishOutput(posted_url=posted_url)