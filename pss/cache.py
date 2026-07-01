"""In-memory cache of Pixel Starships design data.

Crew, item and room definitions rarely change, so we fetch them once and
refresh periodically. This avoids hammering the API on every command and lets
us resolve names <-> ids locally.
"""
from __future__ import annotations

import logging
import time

from .api import PSSApi

log = logging.getLogger("pss.cache")


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


class GameData:
    """Lazily-loaded, periodically-refreshed catalogue of game designs."""

    def __init__(self, api: PSSApi, ttl: int = 3600) -> None:
        self.api = api
        self.ttl = ttl
        self._loaded_at: float = 0.0

        self.characters: dict[int, dict[str, str]] = {}
        self.items: dict[int, dict[str, str]] = {}
        self.rooms: dict[int, dict[str, str]] = {}

        self._char_by_name: dict[str, int] = {}
        self._item_by_name: dict[str, int] = {}

    # -- loading ------------------------------------------------------------
    @property
    def is_stale(self) -> bool:
        return (time.monotonic() - self._loaded_at) > self.ttl or not self.characters

    async def ensure_loaded(self, force: bool = False) -> None:
        if not force and not self.is_stale:
            return
        log.info("Refreshing PSS design data ...")
        chars = await self.api.list_character_designs()
        items = await self.api.list_item_designs()
        try:
            rooms = await self.api.list_room_designs()
        except Exception as exc:  # rooms are non-critical
            log.warning("Could not load room designs: %s", exc)
            rooms = []

        self.characters = {int(c["CharacterDesignId"]): c for c in chars if c.get("CharacterDesignId")}
        self.items = {int(i["ItemDesignId"]): i for i in items if i.get("ItemDesignId")}
        self.rooms = {int(r["RoomDesignId"]): r for r in rooms if r.get("RoomDesignId")}

        self._char_by_name = {
            _norm(c["CharacterDesignName"]): int(c["CharacterDesignId"])
            for c in chars
            if c.get("CharacterDesignName")
        }
        self._item_by_name = {
            _norm(i["ItemDesignName"]): int(i["ItemDesignId"])
            for i in items
            if i.get("ItemDesignName")
        }
        self._loaded_at = time.monotonic()
        log.info(
            "Loaded %d crew, %d items, %d rooms.",
            len(self.characters),
            len(self.items),
            len(self.rooms),
        )

    # -- lookups ------------------------------------------------------------
    def char_name(self, char_id: int | str) -> str:
        try:
            c = self.characters.get(int(char_id))
        except (TypeError, ValueError):
            c = None
        return c["CharacterDesignName"] if c else f"#{char_id}"

    def find_character(self, query: str) -> dict[str, str] | None:
        """Resolve a crew by exact-ish then fuzzy (substring) name match."""
        key = _norm(query)
        if not key:
            return None
        if key in self._char_by_name:
            return self.characters[self._char_by_name[key]]
        matches = [cid for name, cid in self._char_by_name.items() if key in name]
        if matches:
            # Prefer the shortest name (closest match).
            matches.sort(key=lambda cid: len(self.characters[cid].get("CharacterDesignName", "")))
            return self.characters[matches[0]]
        return None

    def find_characters(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        key = _norm(query)
        if not key:
            return []
        out = [self.characters[cid] for name, cid in self._char_by_name.items() if key in name]
        out.sort(key=lambda c: len(c.get("CharacterDesignName", "")))
        return out[:limit]

    def find_item(self, query: str) -> dict[str, str] | None:
        key = _norm(query)
        if not key:
            return None
        if key in self._item_by_name:
            return self.items[self._item_by_name[key]]
        matches = [iid for name, iid in self._item_by_name.items() if key in name]
        if matches:
            matches.sort(key=lambda iid: len(self.items[iid].get("ItemDesignName", "")))
            return self.items[matches[0]]
        return None

    def find_items(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        key = _norm(query)
        if not key:
            return []
        out = [self.items[iid] for name, iid in self._item_by_name.items() if key in name]
        out.sort(key=lambda i: len(i.get("ItemDesignName", "")))
        return out[:limit]
