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

# Internal SpecialAbilityType enum -> in-game ability name.
ABILITY_NAMES = {
    "DeductReload": "System Hack",
    "HealSelfHp": "First Aid",
    "HealSameRoomCharacters": "Healing Rain",
    "HealRoomHp": "Urgent Repair",
    "AddReload": "Rush Command",
    "DamageToRoom": "Ion Blast",
    "DamageToCurrentEnemy": "Critical Strike",
    "DamageToSameRoomCharacters": "Poison Gas",
    "DeductReload_Enemy": "System Hack",
    "SetFire": "Arson",
    "Freeze": "Freeze",
    "FireWalk": "Fire Walk",
    "ProtectRoom": "Stasis Shield",
    "Bloodlust": "Bloodlust",
    "Invulnerability": "Phase Shift",
    "ProtectionShield": "Protection",
    "SpawnCharacter": "Reinforcement",
    "None": "None",
}

# EquipmentMask bit -> equip slot.
EQUIP_SLOTS = [
    (1, "Head"),
    (2, "Body"),
    (4, "Leg"),
    (8, "Weapon"),
    (16, "Accessory"),
    (32, "Pet"),
]


def ability_name(raw: str | None) -> str:
    if not raw or raw == "None":
        return ""
    return ABILITY_NAMES.get(raw, raw)


def equipment_slots(mask: str | int | None) -> str:
    """Decode an EquipmentMask bitmask into a readable slot list."""
    try:
        m = int(mask)
    except (TypeError, ValueError):
        return ""
    slots = [name for bit, name in EQUIP_SLOTS if m & bit]
    return ", ".join(slots)


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


def num(value: str | int | float | None) -> str:
    """Format a numeric value with thousands separators.

    Preserves fractional parts: many crew stats are decimals (e.g. Attack
    ``1.9``), so truncating to int would badly misreport them.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value or "?")
    if f == int(f):
        return f"{int(f):,}"
    return f"{f:,.2f}".rstrip("0").rstrip(".")


# PSS uses sentinel dates (year 0001/1900/2000/2001) to mean "never/unset".
# Rendering those as Discord timestamps produces nonsense like <t:-62135596800:R>.
_SENTINEL_YEAR_CUTOFF = 2001


def parse_pss_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.split(".")[0].replace("Z", "")
    try:
        dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if dt.year <= _SENTINEL_YEAR_CUTOFF:
        return None
    return dt


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
