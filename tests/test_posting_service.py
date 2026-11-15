"""Tests for PostingService concurrency, fault isolation, timeouts, and missing credentials."""

import asyncio
import httpx
import pytest
import respx

from app.config import Settings
from app.platforms.base import PlatformAdapter, PublishOutput
from app.services.posting_service import PostingService


class DummySuccessAdapter(PlatformAdapter):
    def __init__(self, settings: Settings, name: str, url: str) -> None:
        super().__init__(settings)
        self.name = name
        self._url = url

    def missing_credentials(self) -> list[str]:
        return []

    async def _publish(
        self, client: httpx.AsyncClient, message: str, link: str
    ) -> PublishOutput:
        return PublishOutput(posted_url=self._url, public_access_override=True)


class DummyErrorAdapter(PlatformAdapter):
    name = "exploding_platform"

    def missing_credentials(self) -> list[str]:
        return []

    async def _publish(
        self, client: httpx.AsyncClient, message: str, link: str
    ) -> PublishOutput:
        raise RuntimeError(
            f"Auth failed with token {self.settings.github_gist_token}"
        )


class DummySlowAdapter(PlatformAdapter):
    name = "slow_platform"

    def missing_credentials(self) -> list[str]:
        return []

    async def _publish(
        self, client: httpx.AsyncClient, message: str, link: str
    ) -> PublishOutput:
        await asyncio.sleep(5.0)
        return PublishOutput(posted_url="https://slow.example.com/1")


class DummyMissingCredsAdapter(PlatformAdapter):
    name = "unconfigured_platform"

    def missing_credentials(self) -> list[str]:
        return ["SOME_API_KEY"]

    async def _publish(
        self, client: httpx.AsyncClient, message: str, link: str
    ) -> PublishOutput:
        raise AssertionError("Should not be called when credentials are missing")


@pytest.mark.asyncio
async def test_service_all_succeed(configured_settings: Settings) -> None:
    adapters = [
        DummySuccessAdapter(configured_settings, "p1", "https://p1.example.com/1"),
        DummySuccessAdapter(configured_settings, "p2", "https://p2.example.com/2"),
    ]
    service = PostingService(adapters=adapters, settings=configured_settings)
    async with httpx.AsyncClient() as client:
        resp = await service.publish_all(
            client, "Hello https://example.com", "https://example.com"
        )

    assert resp.success is True
    assert [r.platform for r in resp.results] == ["p1", "p2"]
    assert all(r.status == "success" for r in resp.results)
    assert all(r.date is not None and r.time is not None for r in resp.results)


@pytest.mark.asyncio
async def test_service_partial_failure_and_redaction(
    configured_settings: Settings,
) -> None:
    configured_settings.platform_timeout_seconds = 0.2
    adapters = [
        DummySuccessAdapter(configured_settings, "ok_plat", "https://ok.example.com/1"),
        DummyErrorAdapter(configured_settings),
        DummySlowAdapter(configured_settings),
        DummyMissingCredsAdapter(configured_settings),
    ]
    service = PostingService(adapters=adapters, settings=configured_settings)
    async with httpx.AsyncClient() as client:
        resp = await service.publish_all(
            client, "Hello https://example.com", "https://example.com"
        )

    assert resp.success is True
    by_name = {r.platform: r for r in resp.results}

    assert by_name["ok_plat"].status == "success"

    err_res = by_name["exploding_platform"]
    assert err_res.status == "failed"
    assert err_res.posted_url is None
    assert err_res.public_access is False
    assert err_res.date is None
    assert "[REDACTED]" in (err_res.error or "")
    assert configured_settings.github_gist_token not in (err_res.error or "")

    slow_res = by_name["slow_platform"]
    assert slow_res.status == "failed"
    assert "Timed out" in (slow_res.error or "")

    missing_res = by_name["unconfigured_platform"]
    assert missing_res.status == "failed"
    assert missing_res.error == "Missing credentials: SOME_API_KEY"


@pytest.mark.asyncio
async def test_service_all_fail_sets_top_level_false(
    configured_settings: Settings,
) -> None:
    adapters = [
        DummyErrorAdapter(configured_settings),
        DummyMissingCredsAdapter(configured_settings),
    ]
    service = PostingService(adapters=adapters, settings=configured_settings)
    async with httpx.AsyncClient() as client:
        resp = await service.publish_all(
            client, "Hello https://example.com", "https://example.com"
        )

    assert resp.success is False
    assert all(r.status == "failed" for r in resp.results)


@pytest.mark.asyncio
@respx.mock
async def test_read_timeout_is_never_retried_on_post(
    configured_settings: Settings,
) -> None:
    """Verify that ReadTimeout on POST raises immediately without sending a duplicate POST."""
    from app.platforms.github_gist import GitHubGistAdapter

    route = respx.post("https://api.github.com/gists").mock(
        side_effect=httpx.ReadTimeout("Server timed out reading response")
    )
    adapter = GitHubGistAdapter(configured_settings)
    async with httpx.AsyncClient() as client:
        result = await adapter.post(
            client, "Launch https://example.com", "https://example.com"
        )

    assert result.status == "failed"
    assert route.call_count == 1