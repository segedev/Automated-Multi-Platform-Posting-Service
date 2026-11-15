"""Bluesky (AT Protocol) platform adapter with UTF-8 byte facets and AppView verification."""

from datetime import datetime, timezone
import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


def build_link_facet(message: str, link: str) -> list[dict[str, object]]:
    """Compute UTF-8 byte offsets (byteStart, byteEnd) for the CTA link inside `message`.

    AT Protocol requires `byteStart` and `byteEnd` to be zero-indexed byte offsets
    in the UTF-8 encoded string, NOT Python character indices.
    """
    char_start = message.find(link)
    if char_start == -1:
        return []

    prefix_bytes = message[:char_start].encode("utf-8")
    link_bytes = link.encode("utf-8")
    byte_start = len(prefix_bytes)
    byte_end = byte_start + len(link_bytes)

    return [
        {
            "index": {
                "byteStart": byte_start,
                "byteEnd": byte_end,
            },
            "features": [
                {
                    "$type": "app.bsky.richtext.facet#link",
                    "uri": link,
                }
            ],
        }
    ]


class BlueskyAdapter(PlatformAdapter):
    """Publishes a post via AT Protocol XRPC and verifies via public AppView API."""

    name = "bluesky"
    PUBLIC_APPVIEW_URL = (
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread"
    )

    def missing_credentials(self) -> list[str]:
        missing: list[str] = []
        if not self.settings.bluesky_handle.strip():
            missing.append("BLUESKY_HANDLE")
        if not self.settings.bluesky_app_password.strip():
            missing.append("BLUESKY_APP_PASSWORD")
        return missing

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        pds_base = self.settings.bluesky_pds_url.strip().rstrip("/")
        total_budget = max(4.0, self.settings.platform_timeout_seconds - 4.0)

        # Step 1: Authenticate via createSession
        session_url = f"{pds_base}/xrpc/com.atproto.server.createSession"
        session_resp = await request_with_safe_retry(
            client,
            "POST",
            session_url,
            json={
                "identifier": self.settings.bluesky_handle.strip(),
                "password": self.settings.bluesky_app_password.strip(),
            },
            budget_seconds=total_budget * 0.4,
            platform_name=f"{self.name}:auth",
        )
        self.raise_for_response(session_resp, "Bluesky createSession")
        session_data = session_resp.json()

        access_jwt = session_data.get("accessJwt")
        did = session_data.get("did")
        handle = session_data.get("handle") or did
        if not access_jwt or not did:
            raise RuntimeError("Bluesky createSession response missing 'accessJwt' or 'did'")

        # Step 2: Create post record with UTF-8 byte-offset link facet
        record: dict[str, object] = {
            "$type": "app.bsky.feed.post",
            "text": message,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        facets = build_link_facet(message, link)
        if facets:
            record["facets"] = facets

        create_url = f"{pds_base}/xrpc/com.atproto.repo.createRecord"
        create_resp = await request_with_safe_retry(
            client,
            "POST",
            create_url,
            headers={"Authorization": f"Bearer {access_jwt}"},
            json={
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": record,
            },
            budget_seconds=total_budget * 0.6,
            platform_name=f"{self.name}:createRecord",
        )
        self.raise_for_response(create_resp, "Bluesky createRecord")
        create_data = create_resp.json()

        at_uri = str(create_data.get("uri", ""))
        if not at_uri or "/" not in at_uri:
            raise RuntimeError("Bluesky createRecord response missing valid 'uri'")

        rkey = at_uri.rsplit("/", 1)[-1]
        web_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        # Step 3: Verify public access via public.api.bsky.app AppView API
        # (because bsky.app is an SPA that returns HTTP 200 even for non-existent routes)
        is_public = await self._verify_via_appview(client, at_uri)
        return PublishOutput(
            posted_url=web_url,
            public_access_override=is_public,
        )

    async def _verify_via_appview(
        self,
        client: httpx.AsyncClient,
        at_uri: str,
    ) -> bool:
        """Query the unauthenticated Bluesky AppView API to confirm the post is public."""
        try:
            resp = await client.get(
                self.PUBLIC_APPVIEW_URL,
                params={"uri": at_uri, "depth": "0"},
                timeout=self.settings.public_verify_timeout_seconds,
            )
            if resp.status_code != 200:
                return False
            body = resp.json()
            thread = body.get("thread", {})
            return bool(thread.get("post", {}).get("uri") == at_uri)
        except Exception:
            return False