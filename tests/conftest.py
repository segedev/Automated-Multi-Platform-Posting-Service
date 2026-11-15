"""Shared pytest fixtures for mock settings and FastAPI test client."""

from collections.abc import AsyncIterator
import httpx
import pytest
import pytest_asyncio

from app.config import Settings
from app.main import app, get_settings


@pytest.fixture
def configured_settings() -> Settings:
    """Return a Settings object with dummy credentials populated for all 7 platforms."""
    return Settings(
        platform_timeout_seconds=5.0,
        public_verify_timeout_seconds=2.0,
        telegraph_access_token="tph_secret_token_12345",
        github_gist_token="ghp_secret_token_12345",
        mastodon_instance_url="https://mastodon.social",
        mastodon_access_token="masto_secret_token_12345",
        bluesky_pds_url="https://bsky.social",
        bluesky_handle="alice.bsky.social",
        bluesky_app_password="abcd-efgh-ijkl-mnop",
        devto_api_key="devto_secret_key_12345",
        telegram_bot_token="123456789:AAH_secret_bot_token",
        telegram_chat_id="@public_updates_channel",
        discord_webhook_url="https://discord.com/api/webhooks/111222333/discord_secret_webhook_token",
        discord_guild_id="",
    )


@pytest_asyncio.fixture
async def api_client(configured_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Provide an AsyncClient wired to the FastAPI app with overridden settings."""
    app.dependency_overrides[get_settings] = lambda: configured_settings
    async with httpx.AsyncClient(
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
    ) as shared_http_client:
        app.state.http_client = shared_http_client
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client
    app.dependency_overrides.clear()