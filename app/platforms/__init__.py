"""Platform registry providing all configured third-party adapters in deterministic order."""

from app.config import Settings
from app.platforms.base import PlatformAdapter
from app.platforms.bluesky import BlueskyAdapter
from app.platforms.devto import DevToAdapter
from app.platforms.discord import DiscordWebhookAdapter
from app.platforms.github_gist import GitHubGistAdapter
from app.platforms.mastodon import MastodonAdapter
from app.platforms.telegram import TelegramAdapter
from app.platforms.telegraph import TelegraphAdapter

ADAPTER_CLASSES: tuple[type[PlatformAdapter], ...] = (
    TelegraphAdapter,
    GitHubGistAdapter,
    MastodonAdapter,
    BlueskyAdapter,
    DevToAdapter,
    TelegramAdapter,
    DiscordWebhookAdapter,
)


def build_platform_registry(settings: Settings) -> list[PlatformAdapter]:
    """Instantiate all 7 registered platform adapters."""
    return [adapter_cls(settings) for adapter_cls in ADAPTER_CLASSES]