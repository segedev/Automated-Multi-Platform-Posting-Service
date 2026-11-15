"""Application configuration loaded from environment variables and .env file."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings and third-party platform credentials."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Timeouts
    platform_timeout_seconds: float = Field(default=15.0, gt=0.0)
    public_verify_timeout_seconds: float = Field(default=5.0, gt=0.0)

    # 1. Telegraph
    telegraph_access_token: str = Field(default="")

    # 2. GitHub Gist
    github_gist_token: str = Field(default="")

    # 3. Mastodon
    mastodon_instance_url: str = Field(default="https://mastodon.social")
    mastodon_access_token: str = Field(default="")

    # 4. Bluesky
    bluesky_pds_url: str = Field(default="https://bsky.social")
    bluesky_handle: str = Field(default="")
    bluesky_app_password: str = Field(default="")

    # 5. Dev.to
    devto_api_key: str = Field(default="")

    # 6. Telegram
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # 7. Discord
    discord_webhook_url: str = Field(default="")
    discord_guild_id: str = Field(default="")

    def secret_values(self) -> list[str]:
        """Return non-empty sensitive credential values for redaction."""
        candidates = [
            self.telegraph_access_token,
            self.github_gist_token,
            self.mastodon_access_token,
            self.bluesky_app_password,
            self.devto_api_key,
            self.telegram_bot_token,
            self.discord_webhook_url,
        ]
        return [val.strip() for val in candidates if val and len(val.strip()) >= 4]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()