"""Helpers for turning raw PSS attributes into human-friendly text."""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re

RARITY_EMOJI = {
    "Common": "⚪",      # white circle
    "Elite": "\U0001F7E2",   # green
    "Unique": "\U0001F535",  # blue
    "Epic": "\U0001F7E3",    # purple
    "Hero": "\U0001F7E1",    # yellow/gold
    "Special": "\U0001F534", # red
    "Legendary": "\U0001F7E0",  # orange
}

_TAG_RE = re.compile(r"<[^>]+>")


def rarity_icon(rarity: str) -> str:
    return RARITY_EMOJI.get(rarity, "⭐")


def clean_text(raw: str | None) -> str:
    """Strip PSS in-game markup (<color>, <size>, %0a line breaks, ...)."""
    if not raw:
        return ""
    text = unescape(raw)
    text = text.replace("%0a", "\n").replace("%0A", "\n")
    text = _TAG_RE.sub("", text)
    return text.strip()


def num(value: str | int | None) -> str:
    """Format an integer-ish value with thousands separators."""
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value or "?")


def parse_pss_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.split(".")[0].replace("Z", "")
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def relative_time(raw: str | None) -> str:
    """Return a Discord relative timestamp (e.g. '<t:123:R>') or 'unknown'."""
    dt = parse_pss_datetime(raw)
    if dt is None:
        return "unknown"
    return f"<t:{int(dt.timestamp())}:R>"


def stat_line(char: dict[str, str]) -> str:
    """One-line summary of a crew member's max stats."""
    def g(key: str) -> str:
        return num(char.get(key, "?"))

    return (
        f"HP {g('FinalHp')} • ATK {g('FinalAttack')} • "
        f"RPR {g('FinalRepair')} • ABL {g('SpecialAbilityFinalArgument') or char.get('SpecialAbilityArgument', '?')}"
    )
