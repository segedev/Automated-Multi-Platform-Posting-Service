"""Unit tests for all 7 platform adapters verifying payloads, URLs, and edge cases."""

import json
import httpx
import pytest
import respx

from app.config import Settings
from app.platforms.bluesky import BlueskyAdapter, build_link_facet
from app.platforms.devto import DevToAdapter
from app.platforms.discord import DiscordWebhookAdapter
from app.platforms.github_gist import GitHubGistAdapter
from app.platforms.mastodon import MastodonAdapter
from app.platforms.telegram import TelegramAdapter
from app.platforms.telegraph import TelegraphAdapter


def test_bluesky_utf8_byte_offsets_with_multibyte_emojis() -> None:
    """Verify byteStart and byteEnd use UTF-8 byte offsets, not character indices."""
    # Rocket emoji '🚀' is 4 bytes in UTF-8, 1 character in Python str.
    # Party popper '🎉' is 4 bytes in UTF-8, 1 character in Python str.
    message = "🚀🎉 Launch! https://example.com/news"
    link = "https://example.com/news"

    facets = build_link_facet(message, link)
    assert len(facets) == 1
    index = facets[0]["index"]  # type: ignore[index]

    char_start = message.index(link)
    assert char_start == 11  # character offset is 11
    # 2 emojis (8 bytes) + " Launch! " (9 bytes) = 17 bytes
    assert index["byteStart"] == 17
    assert index["byteEnd"] == 17 + len(link.encode("utf-8"))
    assert message.encode("utf-8")[index["byteStart"] : index["byteEnd"]].decode("utf-8") == link


@pytest.mark.asyncio
@respx.mock
async def test_bluesky_adapter_uses_bsky_app_url_and_appview_verification(
    configured_settings: Settings,
) -> None:
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").mock(
        return_value=httpx.Response(
            200,
            json={
                "accessJwt": "jwt_tok_123",
                "did": "did:plc:abcdef123456",
                "handle": "alice.bsky.social",
            },
        )
    )
    create_route = respx.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "uri": "at://did:plc:abcdef123456/app.bsky.feed.post/3lbxyz987",
                "cid": "bafyreicid",
            },
        )
    )
    appview_route = respx.get(
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "thread": {
                    "post": {
                        "uri": "at://did:plc:abcdef123456/app.bsky.feed.post/3lbxyz987"
                    }
                }
            },
        )
    )

    adapter = BlueskyAdapter(configured_settings)
    msg = "🚀 Big news at https://example.com/bsky"
    async with httpx.AsyncClient() as client:
        result = await adapter.post(client, msg, "https://example.com/bsky")

    assert result.status == "success"
    assert result.posted_url == "https://bsky.app/profile/alice.bsky.social/post/3lbxyz987"
    assert result.public_access is True
    assert appview_route.called

    sent_body = json.loads(create_route.calls.last.request.content)
    facet_idx = sent_body["record"]["facets"][0]["index"]
    # '🚀' is 4 bytes + ' Big news at ' is 13 bytes = 17
    assert facet_idx["byteStart"] == 17


@pytest.mark.asyncio
@respx.mock
async def test_telegraph_adapter_success(configured_settings: Settings) -> None:
    respx.post("https://api.telegra.ph/createPage").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "result": {"url": "https://telegra.ph/Update-11-15"}},
        )
    )
    respx.head("https://telegra.ph/Update-11-15").mock(
        return_value=httpx.Response(200)
    )

    adapter = TelegraphAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        result = await adapter.post(
            client, "Check https://example.com", "https://example.com"
        )

    assert result.status == "success"
    assert result.posted_url == "https://telegra.ph/Update-11-15"
    assert result.public_access is True


@pytest.mark.asyncio
@respx.mock
async def test_github_gist_adapter_success(configured_settings: Settings) -> None:
    respx.post("https://api.github.com/gists").mock(
        return_value=httpx.Response(
            201,
            json={"html_url": "https://gist.github.com/user/gist123"},
        )
    )
    respx.head("https://gist.github.com/user/gist123").mock(
        return_value=httpx.Response(200)
    )

    adapter = GitHubGistAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        result = await adapter.post(
            client, "Code at https://example.com", "https://example.com"
        )

    assert result.status == "success"
    assert result.posted_url == "https://gist.github.com/user/gist123"
    assert result.public_access is True


@pytest.mark.asyncio
@respx.mock
async def test_mastodon_adapter_sends_idempotency_key_and_retries_429(
    configured_settings: Settings,
) -> None:
    route = respx.post("https://mastodon.social/api/v1/statuses").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0.05"}, json={"error": "Throttled"}),
            httpx.Response(200, json={"url": "https://mastodon.social/@alice/111222"}),
        ]
    )
    respx.head("https://mastodon.social/@alice/111222").mock(
        return_value=httpx.Response(200)
    )

    adapter = MastodonAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        result = await adapter.post(
            client, "Hello Mastodon https://example.com", "https://example.com"
        )

    assert result.status == "success"
    assert result.posted_url == "https://mastodon.social/@alice/111222"
    assert route.call_count == 2
    first_key = route.calls[0].request.headers.get("Idempotency-Key")
    second_key = route.calls[1].request.headers.get("Idempotency-Key")
    assert first_key and first_key == second_key


@pytest.mark.asyncio
@respx.mock
async def test_devto_adapter_sends_forem_header_and_timestamp_title(
    configured_settings: Settings,
) -> None:
    route = respx.post("https://dev.to/api/articles").mock(
        return_value=httpx.Response(
            201,
            json={"url": "https://dev.to/alice/new-post-123"},
        )
    )
    respx.head("https://dev.to/alice/new-post-123").mock(
        return_value=httpx.Response(200)
    )

    adapter = DevToAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        result = await adapter.post(
            client, "Check out our tool https://example.com", "https://example.com"
        )

    assert result.status == "success"
    assert result.posted_url == "https://dev.to/alice/new-post-123"
    req = route.calls.last.request
    assert req.headers.get("Accept") == "application/vnd.forem.api-v1+json"
    body = json.loads(req.content)
    assert "[" in body["article"]["title"] and "]" in body["article"]["title"]


@pytest.mark.asyncio
@respx.mock
async def test_telegram_adapter_success(configured_settings: Settings) -> None:
    respx.post(
        f"https://api.telegram.org/bot{configured_settings.telegram_bot_token}/sendMessage"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 42,
                    "chat": {"username": "public_updates_channel"},
                },
            },
        )
    )
    respx.head("https://t.me/public_updates_channel/42").mock(
        return_value=httpx.Response(200)
    )

    adapter = TelegramAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        result = await adapter.post(
            client, "Telegram post https://example.com", "https://example.com"
        )

    assert result.status == "success"
    assert result.posted_url == "https://t.me/public_updates_channel/42"
    assert result.public_access is True


@pytest.mark.asyncio
@respx.mock
async def test_discord_adapter_with_and_without_guild_id(
    configured_settings: Settings,
) -> None:
    # Case 1: Discord webhook response includes guild_id
    respx.post(configured_settings.discord_webhook_url).mock(
        return_value=httpx.Response(
            200,
            json={"id": "999", "channel_id": "888", "guild_id": "777"},
        )
    )
    adapter = DiscordWebhookAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        res_with_guild = await adapter.post(
            client, "Discord msg https://example.com", "https://example.com"
        )

    assert res_with_guild.status == "success"
    assert res_with_guild.posted_url == "https://discord.com/channels/777/888/999"
    assert res_with_guild.public_access is False

    # Case 2: Discord webhook response omits guild_id -> does NOT invent @me URL
    respx.post(configured_settings.discord_webhook_url).mock(
        return_value=httpx.Response(
            200,
            json={"id": "999", "channel_id": "888"},
        )
    )
    async with httpx.AsyncClient() as client:
        res_no_guild = await adapter.post(
            client, "Discord msg https://example.com", "https://example.com"
        )

    assert res_no_guild.status == "success"
    assert res_no_guild.posted_url is None
    assert res_no_guild.public_access is False
    assert "guild_id not returned" in (res_no_guild.error or "")