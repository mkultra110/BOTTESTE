"""Asynchronous client for the Pixel Starships public API.

The PSS API returns XML. Most read-only endpoints (player search, fleet
rankings, crew/item designs, daily offers) work anonymously. A handful of
endpoints require an authenticated *device token*; those are only used when a
checksum key is configured (see ``config.PSS_DEVICE_CHECKSUM_KEY``).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import aiohttp

log = logging.getLogger("pss.api")

USER_AGENT = "UnityPlayer/2021.3.33f1 (UnityWebRequest/1.0, libcurl/7.84.0-DEV)"


class PSSApiError(Exception):
    """Raised when the PSS API returns an error or malformed response."""


class PSSApi:
    """Thin async wrapper around the Pixel Starships API."""

    def __init__(
        self,
        host: str = "api.pixelstarships.com",
        language: str = "en",
        checksum_key: str = "",
    ) -> None:
        self.host = host
        self.language = language
        self.checksum_key = checksum_key
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._token_lock = asyncio.Lock()

    # -- lifecycle ----------------------------------------------------------
    async def __aenter__(self) -> "PSSApi":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=25),
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def has_auth(self) -> bool:
        """True when authenticated (token) endpoints can be attempted."""
        return bool(self.checksum_key)

    # -- core request -------------------------------------------------------
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> ET.Element:
        if self._session is None or self._session.closed:
            await self.start()
        url = f"https://{self.host}/{path.lstrip('/')}"
        try:
            async with self._session.get(url, params=params) as resp:
                text = await resp.text()
        except aiohttp.ClientError as exc:  # network-level failure
            raise PSSApiError(f"Network error contacting PSS API: {exc}") from exc

        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise PSSApiError(f"Invalid XML from {path}: {exc}") from exc

        # The API signals errors via an `errorMessage` attribute on the root
        # or first child element.
        for node in (root, *list(root)):
            err = node.attrib.get("errorMessage")
            if err:
                raise PSSApiError(err)
        return root

    # -- authentication (optional) -----------------------------------------
    async def _ensure_token(self) -> str:
        """Return a device access token, generating one if needed.

        Requires ``checksum_key``; raises PSSApiError otherwise.
        """
        if not self.checksum_key:
            raise PSSApiError(
                "This command needs an authenticated PSS device token, which "
                "requires PSS_DEVICE_CHECKSUM_KEY to be configured."
            )
        if self._token:
            return self._token
        async with self._token_lock:
            if self._token:
                return self._token
            self._token = await self._device_login()
            return self._token

    async def _device_login(self) -> str:
        device_key = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        device_type = "DeviceTypeAndroid"
        checksum = hashlib.md5(
            f"{device_key}{now}{device_type}{self.checksum_key}savysoda".encode()
        ).hexdigest()

        params = {
            "deviceKey": device_key,
            "checksum": checksum,
            "isJailBroken": "false",
            "deviceType": device_type,
            "languageKey": self.language,
            "advertisingKey": "",
        }
        url = f"https://{self.host}/UserService/DeviceLogin8"
        async with self._session.post(url, params=params) as resp:
            text = await resp.text()
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise PSSApiError(f"Login returned invalid XML: {exc}") from exc
        node = root.find(".//UserLogin")
        token = node.attrib.get("accessToken") if node is not None else None
        if not token:
            err = (node.attrib.get("errorMessage") if node is not None else None) or "unknown error"
            raise PSSApiError(f"Device login failed: {err}")
        log.info("Obtained PSS device token.")
        return token

    async def _get_auth(self, path: str, params: dict[str, Any] | None = None) -> ET.Element:
        """GET an endpoint that requires an access token, with one retry on
        token expiry."""
        params = dict(params or {})
        params["accessToken"] = await self._ensure_token()
        try:
            return await self._get(path, params)
        except PSSApiError:
            # Token may have expired — refresh once and retry.
            self._token = None
            params["accessToken"] = await self._ensure_token()
            return await self._get(path, params)

    # ======================================================================
    #  Public (no-token) endpoints
    # ======================================================================
    async def search_users(self, name: str) -> list[dict[str, str]]:
        root = await self._get("UserService/SearchUsers", {"searchString": name})
        return [u.attrib for u in root.iter("User")]

    async def top_alliances(self, take: int = 20) -> list[dict[str, str]]:
        root = await self._get(
            "AllianceService/ListAlliancesByRanking",
            {"skip": 0, "take": max(1, min(take, 100))},
        )
        return [a.attrib for a in root.iter("Alliance")]

    async def today_liveops(self) -> dict[str, str]:
        root = await self._get(
            "LiveOpsService/GetTodayLiveOps2",
            {"languageKey": self.language, "deviceType": "DeviceTypeAndroid"},
        )
        node = next(root.iter("LiveOps"), None)
        if node is None:
            raise PSSApiError("No LiveOps data returned.")
        return node.attrib

    async def list_character_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "CharacterService/ListAllCharacterDesigns2",
            {"languageKey": self.language},
        )
        return [c.attrib for c in root.iter("CharacterDesign")]

    async def list_item_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "ItemService/ListItemDesigns2", {"languageKey": self.language}
        )
        return [i.attrib for i in root.iter("ItemDesign")]

    async def list_room_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "RoomService/ListRoomDesigns2", {"languageKey": self.language}
        )
        return [r.attrib for r in root.iter("RoomDesign")]

    async def list_collection_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "CollectionService/ListAllCollectionDesigns",
            {"languageKey": self.language},
        )
        return [c.attrib for c in root.iter("CollectionDesign")]

    async def list_draw_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "CharacterService/ListAllDrawDesigns", {"languageKey": self.language}
        )
        return [d.attrib for d in root.iter("DrawDesign")]

    async def list_achievement_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "AchievementService/ListAchievementDesigns2", {"languageKey": self.language}
        )
        return [a.attrib for a in root.iter("AchievementDesign")]

    async def list_ship_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "ShipService/ListAllShipDesigns2", {"languageKey": self.language}
        )
        return [s.attrib for s in root.iter("ShipDesign")]

    async def list_division_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "DivisionService/ListAllDivisionDesigns2", {"languageKey": self.language}
        )
        return [d.attrib for d in root.iter("DivisionDesign")]

    async def list_alliances_with_division(self) -> list[dict[str, str]]:
        root = await self._get("AllianceService/ListAlliancesWithDivision")
        return [a.attrib for a in root.iter("Alliance")]

    async def list_situation_designs(self) -> list[dict[str, str]]:
        root = await self._get(
            "SituationService/ListSituationDesigns", {"languageKey": self.language}
        )
        return [s.attrib for s in root.iter("SituationDesign")]

    async def list_star_systems(self) -> list[dict[str, str]]:
        root = await self._get("GalaxyService/ListStarSystems")
        return [s.attrib for s in root.iter("StarSystem")]

    async def list_star_system_links(self) -> list[dict[str, str]]:
        root = await self._get("GalaxyService/ListStarSystemLinks")
        return [l.attrib for l in root.iter("StarSystemLink")]

    async def list_sprites(self) -> list[dict[str, str]]:
        """Sprite catalogue: SpriteId -> spritesheet file + crop coordinates.

        Large payload (~4 MB XML); callers should cache the result.
        """
        root = await self._get("FileService/ListSprites")
        return [s.attrib for s in root.iter("Sprite")]

    async def prestige_from(self, char_id: int) -> list[dict[str, str]]:
        try:
            root = await self._get(
                "CharacterService/PrestigeCharacterFrom", {"characterDesignId": char_id}
            )
        except PSSApiError as exc:
            # Common/Special/Legendary crew simply have no combinations.
            if "prestige" in str(exc).lower():
                return []
            raise
        return [p.attrib for p in root.iter("Prestige")]

    async def prestige_to(self, char_id: int) -> list[dict[str, str]]:
        try:
            root = await self._get(
                "CharacterService/PrestigeCharacterTo", {"characterDesignId": char_id}
            )
        except PSSApiError as exc:
            if "prestige" in str(exc).lower():
                return []
            raise
        return [p.attrib for p in root.iter("Prestige")]

    async def price_history(self, item_id: int) -> list[tuple[str, int]]:
        """Return [(date, average_price), ...] daily points for an item.

        Uses the anonymous HistoryService; returns an empty list for items
        with no trading history.
        """
        root = await self._get(
            "HistoryService/PriceHistory", {"itemDesignId": item_id}
        )
        points: list[tuple[str, int]] = []
        for h in root.iter("History"):
            date = h.attrib.get("Date", "")
            try:
                value = int(h.attrib.get("Value", 0))
            except (TypeError, ValueError):
                continue
            points.append((date, value))
        points.sort(key=lambda p: p[0])
        return points

    async def latest_version(self) -> dict[str, str]:
        root = await self._get(
            "SettingService/GetLatestVersion3",
            {"languageKey": self.language, "deviceType": "DeviceTypeAndroid"},
        )
        node = next(root.iter("Setting"), None)
        return node.attrib if node is not None else {}

    # ======================================================================
    #  Authenticated (token) endpoints — only work with a checksum key
    # ======================================================================
    async def top_players(self, take: int = 20) -> list[dict[str, str]]:
        root = await self._get_auth(
            "LadderService/ListUsersByRanking",
            {"from": 1, "to": max(1, min(take, 100))},
        )
        return [u.attrib for u in root.iter("User")]

    async def get_alliance(self, alliance_id: int) -> dict[str, str]:
        root = await self._get_auth(
            "AllianceService/GetAlliance", {"allianceId": alliance_id}
        )
        node = next(root.iter("Alliance"), None)
        if node is None:
            raise PSSApiError("Alliance not found.")
        return node.attrib

    async def alliance_members(self, alliance_id: int) -> list[dict[str, str]]:
        root = await self._get_auth(
            "AllianceService/ListUsers",
            {"allianceId": alliance_id, "skip": 0, "take": 100},
        )
        return [u.attrib for u in root.iter("User")]
