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
        self.collections: dict[int, dict[str, str]] = {}

        # A normalized name can map to several designs (e.g. two "Michelle").
        self._char_by_name: dict[str, list[int]] = {}
        self._item_by_name: dict[str, list[int]] = {}
        self._collection_by_name: dict[str, list[int]] = {}

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
        try:
            collections = await self.api.list_collection_designs()
        except Exception as exc:  # collections are non-critical
            log.warning("Could not load collection designs: %s", exc)
            collections = []

        self.characters = {int(c["CharacterDesignId"]): c for c in chars if c.get("CharacterDesignId")}
        self.items = {int(i["ItemDesignId"]): i for i in items if i.get("ItemDesignId")}
        self.rooms = {int(r["RoomDesignId"]): r for r in rooms if r.get("RoomDesignId")}
        self.collections = {
            int(c["CollectionDesignId"]): c for c in collections if c.get("CollectionDesignId")
        }

        self._char_by_name = self._index_by_name(chars, "CharacterDesignName", "CharacterDesignId")
        self._item_by_name = self._index_by_name(items, "ItemDesignName", "ItemDesignId")
        self._collection_by_name = self._index_by_name(
            collections, "CollectionName", "CollectionDesignId"
        )
        self._loaded_at = time.monotonic()
        log.info(
            "Loaded %d crew, %d items, %d rooms, %d collections.",
            len(self.characters),
            len(self.items),
            len(self.rooms),
            len(self.collections),
        )

    @staticmethod
    def _index_by_name(
        rows: list[dict[str, str]], name_key: str, id_key: str
    ) -> dict[str, list[int]]:
        index: dict[str, list[int]] = {}
        for row in rows:
            name = row.get(name_key)
            rid = row.get(id_key)
            if not name or not rid:
                continue
            index.setdefault(_norm(name), []).append(int(rid))
        return index

    # -- lookups ------------------------------------------------------------
    def char_name(self, char_id: int | str) -> str:
        try:
            c = self.characters.get(int(char_id))
        except (TypeError, ValueError):
            c = None
        return c["CharacterDesignName"] if c else f"#{char_id}"

    def collection_name(self, coll_id: int | str) -> str:
        try:
            c = self.collections.get(int(coll_id))
        except (TypeError, ValueError):
            c = None
        if not c:
            return f"#{coll_id}"
        return c.get("CollectionName") or c.get("CollectionDesignName") or f"#{coll_id}"

    def find_collection(self, query: str) -> dict[str, str] | None:
        key = _norm(query)
        if not key:
            return None
        if key in self._collection_by_name:
            return self.collections[self._collection_by_name[key][0]]
        matches = [cid for name, cids in self._collection_by_name.items() if key in name for cid in cids]
        if matches:
            matches.sort(key=lambda cid: len(self.collections[cid].get("CollectionName", "")))
            return self.collections[matches[0]]
        return None

    def crew_in_collection(self, coll_id: int | str) -> list[dict[str, str]]:
        try:
            cid = int(coll_id)
        except (TypeError, ValueError):
            return []
        return [
            c for c in self.characters.values()
            if c.get("CollectionDesignId") not in (None, "", "0")
            and int(c["CollectionDesignId"]) == cid
        ]

    def find_character(self, query: str) -> dict[str, str] | None:
        """Resolve a crew by exact then fuzzy (substring) name match."""
        key = _norm(query)
        if not key:
            return None
        if key in self._char_by_name:
            return self.characters[self._char_by_name[key][0]]
        matches = [cid for name, cids in self._char_by_name.items() if key in name for cid in cids]
        if matches:
            # Prefer the shortest name (closest match).
            matches.sort(key=lambda cid: len(self.characters[cid].get("CharacterDesignName", "")))
            return self.characters[matches[0]]
        return None

    def find_characters(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        key = _norm(query)
        if not key:
            return []
        out = [
            self.characters[cid]
            for name, cids in self._char_by_name.items()
            if key in name
            for cid in cids
        ]
        out.sort(key=lambda c: len(c.get("CharacterDesignName", "")))
        return out[:limit]

    def find_item(self, query: str) -> dict[str, str] | None:
        key = _norm(query)
        if not key:
            return None
        if key in self._item_by_name:
            return self.items[self._item_by_name[key][0]]
        matches = [iid for name, iids in self._item_by_name.items() if key in name for iid in iids]
        if matches:
            matches.sort(key=lambda iid: len(self.items[iid].get("ItemDesignName", "")))
            return self.items[matches[0]]
        return None

    def find_items(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        key = _norm(query)
        if not key:
            return []
        out = [
            self.items[iid]
            for name, iids in self._item_by_name.items()
            if key in name
            for iid in iids
        ]
        out.sort(key=lambda i: len(i.get("ItemDesignName", "")))
        return out[:limit]
