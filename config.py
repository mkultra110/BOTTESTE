"""Central configuration, loaded from environment variables / .env file."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _clean(value: str | None) -> str:
    return (value or "").strip()


# --- Discord ---------------------------------------------------------------
DISCORD_TOKEN: str = _clean(os.getenv("DISCORD_TOKEN"))
_guild_raw = _clean(os.getenv("DISCORD_GUILD_ID"))
DISCORD_GUILD_ID: int | None = int(_guild_raw) if _guild_raw.isdigit() else None

# --- Pixel Starships API ---------------------------------------------------
PSS_API_HOST: str = _clean(os.getenv("PSS_API_HOST")) or "api.pixelstarships.com"
PSS_LANGUAGE: str = _clean(os.getenv("PSS_LANGUAGE")) or "en"
PSS_DEVICE_CHECKSUM_KEY: str = _clean(os.getenv("PSS_DEVICE_CHECKSUM_KEY"))

# --- Bot metadata ----------------------------------------------------------
BOT_COLOR: int = 0x2ECC71          # embed accent colour
CACHE_TTL_SECONDS: int = 60 * 60   # refresh game design data hourly


def require_token() -> None:
    """Fail fast with a friendly message if the Discord token is missing."""
    if not DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set.\n"
            "Copy .env.example to .env and paste your bot token, or export "
            "DISCORD_TOKEN in the environment."
        )
