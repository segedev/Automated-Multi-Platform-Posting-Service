"""GitHub Gist platform adapter."""

import httpx

from app.platforms.base import PlatformAdapter, PublishOutput
from app.utils.http import request_with_safe_retry


class GitHubGistAdapter(PlatformAdapter):
    """Publishes a public GitHub Gist via the official GitHub REST API."""

    name = "github_gist"
    API_URL = "https://api.github.com/gists"

    def missing_credentials(self) -> list[str]:
        if not self.settings.github_gist_token.strip():
            return ["GITHUB_GIST_TOKEN"]
        return []

    async def _publish(
        self,
        client: httpx.AsyncClient,
        message: str,
        link: str,
    ) -> PublishOutput:
        headers = {
            "Authorization": f"Bearer {self.settings.github_gist_token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {
            "description": f"Automated Post - {link}",
            "public": True,
            "files": {
                "announcement.md": {
                    "content": message,
                }
            },
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
        self.raise_for_response(response, "GitHub Gist")

        data = response.json()
        html_url = data.get("html_url")
        if not html_url:
            raise RuntimeError("GitHub Gist response missing 'html_url'")

        return PublishOutput(posted_url=str(html_url))