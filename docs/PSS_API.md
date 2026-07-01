# Pixel Starships API — reference

Catalogue of the Pixel Starships (PSS) API endpoints, verified live against
`https://api.pixelstarships.com`. Responses are **XML**. Most read-only
endpoints work **anonymously**; a subset require an authenticated device
token (see [Authentication](#authentication)).

> This is a read-only reference for the companion bot. It intentionally omits
> account-mutating endpoints (login, buy, upgrade, attack, collect, …) — the
> bot does not automate gameplay.

## Authentication

- **Anonymous** — no token needed. Every `List*`/`Get*`/`Search*` design and
  ranking endpoint below.
- **Token** — pass `accessToken=<token>` obtained from `DeviceLogin*`, which
  is derived from a checksum key intentionally not shipped in this repo. Set
  `PSS_DEVICE_CHECKSUM_KEY` to unlock these. Kept optional on purpose.

---

## ✅ Anonymous endpoints (used or usable by the bot)

| Endpoint | Params | Returns | Bot use |
|---|---|---|---|
| `SettingService/GetLatestVersion3` | `languageKey`, `deviceType` | server settings, versions | health / version check |
| `UserService/SearchUsers` | `searchString` | **exact-name** player match (≤1 user) | `/player` |
| `AllianceService/ListAlliancesByRanking` | `skip`, `take` | top fleets (trophies, Score, DivisionDesignId, NumberOfMembers) | `/fleet-top` |
| `AllianceService/ListAlliancesWithDivision` | — | fleets grouped by tournament division | division standings |
| `LiveOpsService/GetTodayLiveOps2` | `languageKey`, `deviceType` | daily reward, sale, shop, cargo, news, featured crew | `/daily` |
| `CharacterService/ListAllCharacterDesigns2` | `languageKey` | full crew catalogue (53 attrs each) | `/crew`, cache |
| `CharacterService/PrestigeCharacterFrom` | `characterDesignId` | combos this crew prestiges into | `/prestige` |
| `CharacterService/PrestigeCharacterTo` | `characterDesignId` | pairs that build this crew | `/prestige-recipes` |
| `CharacterService/ListAllCharacterDesignActions` | — | ability trigger conditions | (future) ability details |
| `CharacterService/ListAllDrawDesigns` | — | recruit/gacha odds & costs | (future) draw odds |
| `CollectionService/ListAllCollectionDesigns` | `languageKey` | collections, combo bonuses | crew collection names |
| `ItemService/ListItemDesigns2` | `languageKey` | full item catalogue (55 attrs each) | `/item`, cache |
| `ItemService/ListItemDesignActions` | — | item use effects | (future) item actions |
| `RoomService/ListRoomDesigns2` | `languageKey` | ship rooms (power, capacity, reload) | cache / (future) `/room` |
| `ShipService/ListAllShipDesigns2` | `languageKey` | ship hulls (rows, level, mask) | (future) `/ship` |
| `AchievementService/ListAchievementDesigns2` | `languageKey` | achievements + rewards | (future) `/achievements` |
| `ChallengeService/ListAllChallengeDesigns2` | — | PvP challenge events | (future) events |
| `DivisionService/ListAllDivisionDesigns2` | — | tournament division reward tiers | (future) tourney info |
| `HistoryService/PriceHistory` | `itemDesignId` | daily market price history | (future) price charts/alerts |
| `GalaxyService/ListStarSystems` | — | star system names, lore, coords | (future) galaxy map/lore |
| `GalaxyService/ListStarSystemLinks` | — | galaxy map graph edges | (future) route/pathfinding |
| `GalaxyService/ListMarkerGeneratorDesigns` | — | galaxy event/NPC spawn rules | (future) galaxy events |
| `BackgroundService/ListBackgrounds` | — | battle/starfield backgrounds | design reference |
| `AnimationService/ListAnimations` | — | visual-effect metadata | sprite/FX reference |
| `FileService/ListFiles4` | — | file id → asset filename | sprite URL building |
| `FileService/ListSprites` / `ListSprites2` | — | sprite id → sheet coordinates | icon cropping/rendering |

Notes verified live (2026-07-01):
- `GalaxyService/ListPlanets` returns an empty list (feature unused) — no bot value.
- `HistoryService/PriceHistory` returns an empty `<Histories>` for many items;
  populated only for actively-traded ones.

---

## 🔒 Token-required endpoints

| Endpoint | Params | Returns | Bot use |
|---|---|---|---|
| `LadderService/ListUsersByRanking` | `accessToken`, `from`, `to` | global player leaderboard | `/top-players` |
| `AllianceService/GetAlliance` | `accessToken`, `allianceId` | fleet details | (auth) fleet lookup |
| `AllianceService/ListUsers` | `accessToken`, `allianceId` | fleet member list | (auth) roster |
| `AllianceService/SearchAlliances` | `accessToken`, `name` | fleet search by name | (auth) fleet search |
| `ShipService/InspectShip2` | `accessToken`, `userId` | player ship layout & crew | (auth) ship inspect |
| `MessageService/ListActiveMarketplaceMessages5` | `accessToken`, filters | live marketplace listings | (auth) real market prices |

---

## Field quirks worth knowing (learned from the live audit)

- **Decimal stats**: crew `Final*` stats are often decimals (`FinalAttack="1.9"`).
  Never truncate to int.
- **Sentinel dates**: unset dates come back as year `0001`/`1900`/`2000`/`2001`
  (e.g. `VipExpiryDate`, `AllianceJoinDate`). Treat these as "never".
- **`SearchUsers` is exact-match**: it returns at most one user, matched on the
  full name (case-insensitive) — not a prefix/substring search.
- **`LastAlertDate` ≈ now** for every player; it is *not* a last-seen signal.
  Use `LastHeartBeatDate` / `LastLoginDate`.
- **`LimitedCatalogQuantity`** in LiveOps is *remaining stock*, not a bundle
  size. `LimitedCatalogRestockQuantity` is the restock amount.
- **Item ref lists** (`Ingredients`, `Content`, `DailyItemRewards`, `CargoItems`)
  are `|`-separated; each entry is `idxqty` or `kind:idxqty` (e.g.
  `item:101x6`). Prices (`CargoPrices`) are `|`-separated `currency:amount`.
- **`SaleRewardString`** encodes the real-money price: `item:1187x[USD/2]` → USD 2.
- **`SpecialAbilityType`** is an internal enum (`DeductReload`, `HealSelfHp`, …);
  map it to the in-game name for display (see `pss/formatting.py`).
- **`EquipmentMask`** is a bitmask: 1 Head, 2 Body, 4 Leg, 8 Weapon,
  16 Accessory, 32 Pet.
- **Duplicate names exist** (two crew named "Michelle"): index names to a list
  of ids, not a single id.
- **`MarketPrice`/`FairPrice`** on item designs are static catalogue values, not
  live market data. Live prices need the token-gated marketplace endpoint.
