"""End-to-end integration tests for POST /posting and GET /health."""

import httpx
import pytest
import respx


@pytest.mark.asyncio
async def test_health_endpoint(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_posting_endpoint_validation_error_format(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post(
        "/posting",
        json={"message": "No link in this message"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "Validation error"
    assert isinstance(data["details"], list)
    assert any("CTA link" in detail for detail in data["details"])


@pytest.mark.asyncio
@respx.mock
async def test_posting_endpoint_runs_all_7_platforms(
    api_client: httpx.AsyncClient,
) -> None:
    # Mock all 7 platforms
    respx.post("https://api.telegra.ph/createPage").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"url": "https://telegra.ph/Test-11-15"}}
        )
    )
    respx.head("https://telegra.ph/Test-11-15").mock(return_value=httpx.Response(200))

    respx.post("https://api.github.com/gists").mock(
        return_value=httpx.Response(
            201, json={"html_url": "https://gist.github.com/u/1"}
        )
    )
    respx.head("https://gist.github.com/u/1").mock(return_value=httpx.Response(200))

    respx.post("https://mastodon.social/api/v1/statuses").mock(
        return_value=httpx.Response(
            200, json={"url": "https://mastodon.social/@u/1"}
        )
    )
    respx.head("https://mastodon.social/@u/1").mock(return_value=httpx.Response(200))

    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").mock(
        return_value=httpx.Response(
            200,
            json={
                "accessJwt": "jwt",
                "did": "did:plc:123",
                "handle": "alice.bsky.social",
            },
        )
    )
    respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").mock(
        return_value=httpx.Response(
            200,
            json={"uri": "at://did:plc:123/app.bsky.feed.post/rk1", "cid": "cid1"},
        )
    )
    respx.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread").mock(
        return_value=httpx.Response(
            200,
            json={"thread": {"post": {"uri": "at://did:plc:123/app.bsky.feed.post/rk1"}}},
        )
    )

    respx.post("https://dev.to/api/articles").mock(
        return_value=httpx.Response(201, json={"url": "https://dev.to/u/post-1"})
    )
    respx.head("https://dev.to/u/post-1").mock(return_value=httpx.Response(200))

    respx.post(
        "https://api.telegram.org/bot123456789:AAH_secret_bot_token/sendMessage"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 10,
                    "chat": {"username": "public_updates_channel"},
                },
            },
        )
    )
    respx.head("https://t.me/public_updates_channel/10").mock(
        return_value=httpx.Response(200)
    )

    respx.post(
        "https://discord.com/api/webhooks/111222333/discord_secret_webhook_token"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "m1", "channel_id": "c1", "guild_id": "g1"}
        )
    )

    response = await api_client.post(
        "/posting",
        json={"message": "Check out our latest business platform https://example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["results"]) == 7
    platforms = [item["platform"] for item in body["results"]]
    assert platforms == [
        "telegraph",
        "github_gist",
        "mastodon",
        "bluesky",
        "devto",
        "telegram",
        "discord",
    ]
    assert all(item["status"] == "success" for item in body["results"])