"""Telegram configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from valuecell.server.config.settings import get_settings


@dataclass(slots=True)
class TelegramConfig:
    """Runtime configuration for the Telegram bot."""

    bot_token: str
    webhook_url: Optional[str] = None
    parse_mode: str = "Markdown"
    request_timeout: float = 30.0
    polling_interval: float = 0.5

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        """Load configuration from environment variables via Settings."""
        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required for Telegram integration")

        return cls(
            bot_token=token,
            webhook_url=settings.TELEGRAM_WEBHOOK_URL,
            parse_mode=settings.TELEGRAM_PARSE_MODE,
            request_timeout=settings.TELEGRAM_REQUEST_TIMEOUT,
            polling_interval=settings.TELEGRAM_POLLING_INTERVAL,
        )
