"""Pixel Starships community website.

FastAPI + Jinja2, server-rendered. Reuses the same verified PSS API client
and design-data cache as the Discord bot (read-only, anonymous endpoints).

Run locally:
    uvicorn web.app:app --reload
"""
from __future__ import annotations

import asyncio
import calendar
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from pss.api import PSSApi, PSSApiError
from pss.cache import GameData
from pss.formatting import (
    ability_name,
    clean_text,
    equipment_slots,
    interpolate_stat,
    num,
    parse_pss_datetime,
    rarity_icon,
)

log = logging.getLogger("web")

WEB_DIR = os.path.dirname(os.path.abspath(__file__))

# --- shared state -----------------------------------------------------------
api = PSSApi(host=config.PSS_API_HOST, language=config.PSS_LANGUAGE,
             checksum_key=config.PSS_DEVICE_CHECKSUM_KEY)
data = GameData(api, ttl=config.CACHE_TTL_SECONDS)

# Small TTL cache for live (non-design) endpoints so we never hammer the API.
# Per-key locks prevent a thundering herd: on a cold/expired key, one request
# runs the factory while concurrent ones wait and reuse its result.
_live_cache: dict[str, tuple[float, object]] = {}
_live_locks: dict[str, asyncio.Lock] = {}


async def cached(key: str, ttl: float, factory):
    hit = _live_cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    lock = _live_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _live_cache.get(key)  # re-check: another task may have filled it
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await factory()
        _live_cache[key] = (time.monotonic(), value)
        return value


# --- daily archive (liveops + fleet standings) ------------------------------
# History cannot be backfilled, so snapshots run from day one. Stored as
# JSON-lines, one file per dataset, deduped by UTC date.
ARCHIVE_DIR = os.environ.get("PSS_ARCHIVE_DIR", os.path.join(os.getcwd(), "data", "archive"))


def _archive_has(path: str, date: str) -> bool:
    """True if a snapshot for `date` is already archived.

    Records put "date" first, so checking each line's head is enough — and
    unlike a fixed-size tail read, it works even though a fleets line is
    ~85 KB. Files grow one line per day, so the scan stays cheap.
    """
    if not os.path.exists(path):
        return False
    needles = (f'"date": "{date}"', f'"date":"{date}"')
    try:
        with open(path, errors="ignore") as fh:
            return any(n in line[:64] for line in fh for n in needles)
    except OSError:
        return False


async def _archive_once() -> None:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ops_path = os.path.join(ARCHIVE_DIR, "liveops.jsonl")
    fleets_path = os.path.join(ARCHIVE_DIR, "fleets.jsonl")
    if not _archive_has(ops_path, today):
        ops = await api.today_liveops()
        with open(ops_path, "a") as fh:
            fh.write(json.dumps({"date": today, "liveops": ops}) + "\n")
        log.info("Archived liveops for %s", today)
    if not _archive_has(fleets_path, today):
        fleets = await api.top_alliances(take=100)
        with open(fleets_path, "a") as fh:
            fh.write(json.dumps({"date": today, "fleets": fleets}) + "\n")
        log.info("Archived fleet standings for %s", today)


async def _archive_loop() -> None:
    while True:
        try:
            await _archive_once()
        except Exception as exc:  # non-fatal; retried next cycle
            log.warning("Archive snapshot failed: %s", exc)
        await asyncio.sleep(6 * 3600)


def tournament_info(now: datetime | None = None) -> dict:
    """Tournament runs the last week of each month (7 days before month end)."""
    now = now or datetime.now(timezone.utc)
    last_day = calendar.monthrange(now.year, now.month)[1]
    start = datetime(now.year, now.month, last_day, tzinfo=timezone.utc) - \
        timedelta(days=6)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    if now > end:  # already past: next month
        month = now.month % 12 + 1
        year = now.year + (1 if month == 1 else 0)
        last_day = calendar.monthrange(year, month)[1]
        start = datetime(year, month, last_day, tzinfo=timezone.utc) - \
            timedelta(days=6)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if now >= start:
        days_left = (end - now).days
        return {"live": True, "label": f"Tournament finals LIVE — ends in {days_left + 1}d"}
    delta = start - now
    return {"live": False, "label": f"Tournament finals in {delta.days}d {delta.seconds // 3600}h"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await api.start()
    try:
        await data.ensure_loaded()
    except Exception as exc:  # pragma: no cover - non fatal, retried on demand
        log.warning("Initial data load failed: %s", exc)
    archive_task = asyncio.create_task(_archive_loop())
    yield
    archive_task.cancel()
    await api.close()


app = FastAPI(title="PSS Companion", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")

import jinja2  # noqa: E402

templates = Jinja2Templates(directory=os.path.join(WEB_DIR, "templates"))
# Missing attrs reach filters as jinja2.Undefined, which float() rejects with
# UndefinedError rather than the TypeError num() handles — map those to "?".
templates.env.filters["num"] = (
    lambda v: "?" if isinstance(v, jinja2.Undefined) else num(v))
templates.env.filters["clean"] = clean_text
templates.env.filters["rarity_icon"] = rarity_icon
templates.env.filters["ability"] = ability_name
templates.env.filters["slots"] = equipment_slots
templates.env.filters["rarity_class"] = lambda r: "r-" + (r or "Common").lower()
templates.env.globals["now"] = time.time

# Sprites are served through our own /sprite/{file}.png proxy (disk-cached)
# rather than hotlinking Savy's S3 from every visitor's browser.
SPRITE_CDN = "/sprite"
SPRITE_UPSTREAM = "https://pixelstarships.s3.amazonaws.com"
SPRITE_CACHE_DIR = os.environ.get(
    "PSS_SPRITE_CACHE_DIR", os.path.join(os.getcwd(), "data", "sprites"))


def sprite_html(sprite_id, target_height: int = 32, alt: str = "") -> "Markup":
    """Inline game sprite cropped from its spritesheet, scaled to fit
    ``target_height`` pixels (sprites vary wildly in native size).

    Falls back to empty output when the sprite is unknown, so pages degrade
    gracefully if the sprite catalogue failed to load.
    """
    info = data.sprite_info(sprite_id)
    if not info:
        return Markup("")
    w, h = info["w"], info["h"]
    scale = round(min(target_height / h, 4.0), 3)
    return Markup(
        f'<span class="sprite-box" role="img" aria-label="{alt}" '
        f'style="width:{round(w * scale)}px;height:{round(h * scale)}px">'
        f'<span class="sprite" style="width:{w}px;height:{h}px;'
        f"background-image:url('{SPRITE_CDN}/{info['file']}.png');"
        f'background-position:-{info["x"]}px -{info["y"]}px;'
        f'transform:scale({scale})"></span></span>'
    )


from markupsafe import Markup  # noqa: E402  (used by sprite_html)

templates.env.globals["sprite"] = sprite_html


def render(request: Request, template: str, **ctx) -> HTMLResponse:
    # Freshness is a product feature: every page shows how old the data is.
    age_min = int((time.monotonic() - data._loaded_at) / 60) if data._loaded_at else None
    ctx.setdefault("data_age_min", age_min)
    return templates.TemplateResponse(request, template, ctx)


# --- daily deal verdict ------------------------------------------------------
def _percentile_top(peers: list[float], value: float) -> int:
    """Return the 'top N%' rank of value among peers (lower = better)."""
    if not peers:
        return 100
    better = sum(1 for p in peers if p > value)
    return max(1, round(better / len(peers) * 100))


def _crew_verdict(crew: dict[str, str]) -> dict | None:
    """Percentile ranks of a crew's key stats vs same-rarity peers."""
    if not crew:
        return None
    rarity = crew.get("Rarity")
    peers = [c for c in data.characters.values() if c.get("Rarity") == rarity]

    def fval(c: dict[str, str], key: str) -> float:
        try:
            return float(c.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    stats = []
    for label, key in (("ATK", "FinalAttack"), ("HP", "FinalHp"),
                       ("RPR", "FinalRepair"), ("ABL", "SpecialAbilityFinalArgument")):
        v = fval(crew, key)
        if v <= 0:
            continue
        pct = _percentile_top([fval(p, key) for p in peers], v)
        stats.append({"label": label, "top": pct, "value": v})
    stats.sort(key=lambda s: s["top"])
    best = stats[0] if stats else None
    return {"stats": stats[:3], "best": best, "peer_count": len(peers), "rarity": rarity}


def _offer_recurrence(cat_type: str | None, cat_arg: str | None) -> dict | None:
    """How often today's shop offer appeared in our own LiveOps archive.

    Matches on type AND argument (argument ids are only unique per type).
    Synchronous file I/O — call via asyncio.to_thread from async routes.
    """
    if not cat_type or not cat_arg:
        return None
    path = os.path.join(ARCHIVE_DIR, "liveops.jsonl")
    if not os.path.exists(path):
        return None
    seen: list[str] = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ops = row.get("liveops", {})
                if (ops.get("LimitedCatalogType") == cat_type
                        and ops.get("LimitedCatalogArgument") == cat_arg):
                    seen.append(row.get("date", ""))
    except OSError:
        return None
    if not seen:
        return None
    # Unique dates only: legacy files may hold same-day duplicates from
    # before the dedupe fix.
    unique = sorted(set(seen))
    return {"times": len(unique), "tracked_since": unique[0]}


async def _item_deal_verdict(ops: dict[str, str], sale_item: dict | None) -> dict | None:
    """Compare today's shop offer price against the item's market history."""
    if not sale_item or ops.get("LimitedCatalogCurrencyType") != "Starbux":
        return None
    try:
        offer_price = int(ops.get("LimitedCatalogCurrencyAmount", 0) or 0)
        item_id = int(sale_item["ItemDesignId"])
    except (TypeError, ValueError):
        return None
    if offer_price <= 0:
        return None
    try:
        history = await cached(f"price:{item_id}", 3600, lambda: api.price_history(item_id))
    except PSSApiError:
        history = []
    # Ignore zero-price days (no trades recorded).
    priced = [(d, v) for d, v in history if v > 0]
    if len(priced) < 7:
        return {"offer": offer_price, "verdict": "unknown",
                "note": "Not enough market history to compare against."}
    recent = [v for _, v in priced[-7:]]
    typical = sum(recent) / len(recent)
    if typical <= 0:
        return {"offer": offer_price, "verdict": "unknown",
                "note": "Not enough market history to compare against."}
    diff_pct = round((offer_price - typical) / typical * 100)
    if diff_pct <= -15:
        verdict, note = "good", f"~{-diff_pct}% below the recent market price"
    elif diff_pct >= 15:
        verdict, note = "bad", f"~{diff_pct}% above the recent market price"
    else:
        verdict, note = "fair", "close to the recent market price"
    return {"offer": offer_price, "typical": round(typical),
            "lo": min(recent), "hi": max(recent),
            "diff_pct": diff_pct, "verdict": verdict, "note": note}


# --- pages ------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    await data.ensure_loaded()
    ops = await cached("liveops", 300, api.today_liveops)
    fleets = await cached("fleets", 300, lambda: api.top_alliances(take=10))
    featured = {
        "common": data.characters.get(int(ops.get("CommonCrewId", 0) or 0)),
        "hero": data.characters.get(int(ops.get("HeroCrewId", 0) or 0)),
    }
    sale_item = None
    try:
        if ops.get("LimitedCatalogType") == "Item":
            sale_item = data.items.get(int(ops.get("LimitedCatalogArgument", 0) or 0))
    except ValueError:
        pass
    deal = await _item_deal_verdict(ops, sale_item)
    hero_verdict = _crew_verdict(featured["hero"]) if featured["hero"] else None
    recurrence = await asyncio.to_thread(
        _offer_recurrence, ops.get("LimitedCatalogType"), ops.get("LimitedCatalogArgument"))
    return render(request, "home.html", ops=ops, fleets=fleets, featured=featured,
                  sale_item=sale_item, news=clean_text(ops.get("News")),
                  tournament=tournament_info(), deal=deal,
                  hero_verdict=hero_verdict, recurrence=recurrence)


@app.get("/search", response_class=HTMLResponse)
async def global_search(request: Request, q: str = ""):
    """One search box across crew, items, rooms and ships."""
    await data.ensure_loaded()
    ql = q.lower().strip()
    results: dict[str, list] = {"crew": [], "items": [], "rooms": [], "ships": []}
    if ql:
        results["crew"] = [c for c in data.characters.values()
                           if ql in c.get("CharacterDesignName", "").lower()][:20]
        results["items"] = [i for i in data.items.values()
                            if ql in i.get("ItemDesignName", "").lower()][:20]
        results["rooms"] = data.find_rooms(ql, limit=20)
        results["ships"] = [s for s in data.ships.values()
                            if ql in s.get("ShipDesignName", "").lower()][:20]
    total = sum(len(v) for v in results.values())
    return render(request, "search.html", q=q, results=results, total=total)


@app.get("/rooms", response_class=HTMLResponse)
async def rooms_page(request: Request, q: str = "", type: str = ""):
    await data.ensure_loaded()
    rooms = list(data.rooms.values())
    if q:
        rooms = [r for r in rooms if q.lower() in r.get("RoomName", "").lower()]
    if type:
        rooms = [r for r in rooms if r.get("RoomType") == type]
    rooms.sort(key=data._room_sort_key)
    types = sorted({r.get("RoomType", "") for r in data.rooms.values()})
    return render(request, "rooms.html", rooms=rooms[:200], total=len(rooms),
                  q=q, type=type, types=types)


@app.get("/ships", response_class=HTMLResponse)
async def ships_page(request: Request, q: str = ""):
    await data.ensure_loaded()
    ships = list(data.ships.values())
    if q:
        ships = [s for s in ships if q.lower() in s.get("ShipDesignName", "").lower()]
    ships.sort(key=lambda s: (int(s.get("ShipLevel", 0) or 0), s.get("ShipDesignName", "")))
    return render(request, "ships.html", ships=ships[:200], total=len(ships), q=q)


RARITY_SCALE = ["Common", "Elite", "Unique", "Epic", "Hero", "Legendary", "Special"]


def _draw_rarity(idx: str | None) -> str:
    try:
        return RARITY_SCALE[int(idx)]
    except (TypeError, ValueError, IndexError):
        return "?"


def _draw_cost(raw: str | None) -> str:
    if not raw or ":" not in raw:
        return raw or "?"
    kind, _, amount = raw.partition(":")
    return f"{num(amount)} {kind.capitalize()}"


@app.get("/recruit", response_class=HTMLResponse)
async def recruit_page(request: Request):
    try:
        draws = await cached("draws", 3600, api.list_draw_designs)
    except PSSApiError:
        draws = []
    draws = sorted(draws, key=lambda d: int(d.get("OrderIndex", 0) or 0))
    rows = []
    for d in draws:
        lo, hi = _draw_rarity(d.get("MinCrewRarity")), _draw_rarity(d.get("MaxCrewRarity"))
        rows.append({
            "name": d.get("DrawName", "?"),
            "desc": clean_text(d.get("DrawDescription")),
            "cost": _draw_cost(d.get("Cost")),
            "rarity": lo if lo == hi else f"{lo} → {hi}",
            "rarity_class": "r-" + hi.lower(),
            "increase": d.get("CostPercentageIncrease"),
            "pity": d.get("GuaranteedHeroicDraws"),
        })
    return render(request, "recruit.html", draws=rows)


def _parse_reward(raw: str | None) -> dict | None:
    """Parse an achievement RewardString ('starbux:5', 'item:749x1') to a
    renderable reward with an optional item link."""
    if not raw or ":" not in raw:
        return None
    kind, _, rest = raw.partition(":")
    amount = rest.split("x")[0]
    if kind == "item":
        it = data.items.get(int(amount)) if amount.isdigit() else None
        qty = rest.split("x")[1] if "x" in rest else "1"
        return {"kind": "item", "item_id": amount,
                "label": (it.get("ItemDesignName") if it else f"item #{amount}"),
                "qty": qty}
    return {"kind": kind, "label": f"{num(amount)} {kind.capitalize()}"}


@app.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request, type: str = "", hidden: str = ""):
    await data.ensure_loaded()
    try:
        ach = await cached("achievements", 3600, api.list_achievement_designs)
    except PSSApiError:
        ach = []
    types = sorted({a.get("AchievementType", "") for a in ach})
    shown = ach
    if type:
        shown = [a for a in shown if a.get("AchievementType") == type]
    if hidden != "1":
        shown = [a for a in shown if a.get("IsHidden") != "true"]
    shown = sorted(shown, key=lambda a: (a.get("AchievementType", ""),
                                         int(a.get("OrderIndex", 0) or 0)))
    rows = [{
        "title": a.get("AchievementTitle", "?"),
        "desc": clean_text(a.get("AchievementDescription")),
        "type": a.get("AchievementType", ""),
        "sprite": a.get("SpriteId"),
        "reward": _parse_reward(a.get("RewardString")),
        "monthly": a.get("DurationType") == "Monthly",
        "hidden": a.get("IsHidden") == "true",
    } for a in shown]
    hidden_count = sum(1 for a in ach if a.get("IsHidden") == "true")
    return render(request, "achievements.html", rows=rows, types=types,
                  type=type, show_hidden=(hidden == "1"),
                  total=len(shown), hidden_count=hidden_count)


# --- events (situations) -----------------------------------------------------
def _parse_change(raw: str | None) -> dict | None:
    """Parse a situation ChangeArgumentString like 'item:713x1' or
    'character:327' into a linkable drop reference."""
    if not raw or ":" not in raw:
        return None
    kind, _, rest = raw.partition(":")
    ref = rest.split("x")[0]
    if kind == "item" and ref.isdigit():
        it = data.items.get(int(ref))
        return {"kind": "item", "id": ref,
                "label": it.get("ItemDesignName") if it else f"item #{ref}",
                "sprite": it.get("ImageSpriteId") if it else None}
    if kind == "character" and ref.isdigit():
        c = data.characters.get(int(ref))
        return {"kind": "crew", "id": ref,
                "label": c.get("CharacterDesignName") if c else f"crew #{ref}",
                "sprite": c.get("ProfileSpriteId") if c else None}
    return None


def _situations_rows(situations: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = []
    for s in situations:
        start = parse_pss_datetime(s.get("FromDate"))
        end = parse_pss_datetime(s.get("EndDate"))
        rows.append({
            "name": s.get("SituationName", "?"),
            "desc": clean_text(s.get("SituationDescription")),
            "sprite": s.get("IconSpriteId"),
            "start": start.strftime("%Y-%m-%d") if start else "?",
            "end": end.strftime("%Y-%m-%d") if end else "?",
            "active": bool(start and end and start <= now <= end),
            "chance": s.get("Chance"),
            "limit": s.get("DailyOccurrenceLimit"),
            "drop": _parse_change(s.get("ChangeArgumentString")),
            "type": s.get("ChangeType", ""),
            "_end_sort": end or datetime.min.replace(tzinfo=timezone.utc),
        })
    # Active first, then most recent past events.
    rows.sort(key=lambda r: (not r["active"], -r["_end_sort"].timestamp()))
    return rows


async def _event_sources(kind: str, ref_id: int) -> list[dict]:
    """Situations that drop this crew/item (loot-source cross-links)."""
    try:
        situations = await cached("situations", 3600, api.list_situation_designs)
    except PSSApiError:
        return []
    needle = f"{kind}:{ref_id}"
    out = []
    for s in situations:
        arg = s.get("ChangeArgumentString", "") or ""
        if arg == needle or arg.startswith(needle + "x"):
            end = parse_pss_datetime(s.get("EndDate"))
            out.append({"name": s.get("SituationName", "?"),
                        "chance": s.get("Chance"),
                        "end": end.strftime("%Y-%m-%d") if end else "?"})
    return out


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    await data.ensure_loaded()
    try:
        situations = await cached("situations", 3600, api.list_situation_designs)
    except PSSApiError:
        situations = []
    rows = _situations_rows(situations)
    active = [r for r in rows if r["active"]]
    return render(request, "events.html", rows=rows, active_count=len(active))


def _galaxy_map(systems: list[dict], links: list[dict]) -> dict | None:
    """Project star systems onto an SVG plane and prepare link segments."""
    pts = {}
    for s in systems:
        try:
            pts[int(s["StarSystemId"])] = (int(s.get("X", 0) or 0), int(s.get("Y", 0) or 0))
        except (KeyError, ValueError):
            continue
    if not pts:
        return None
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h, pad = 900, 640, 40
    sx = (w - 2 * pad) / ((maxx - minx) or 1)
    sy = (h - 2 * pad) / ((maxy - miny) or 1)

    def proj(x, y):
        # flip Y so the in-game "up" points up on screen
        return (round(pad + (x - minx) * sx, 1), round(pad + (maxy - y) * sy, 1))

    nodes = []
    for s in systems:
        try:
            sid = int(s["StarSystemId"])
        except (KeyError, ValueError):
            continue
        px, py = proj(*pts[sid])
        nodes.append({"id": sid, "x": px, "y": py,
                      "title": s.get("StarSystemTitle", f"System {sid}"),
                      "sprite": s.get("IconSpriteId"),
                      "desc": clean_text(s.get("StarSystemDescription"))})
    segs = []
    for l in links:
        try:
            a, b = int(l["FromStarSystemId"]), int(l["ToStarSystemId"])
        except (KeyError, ValueError):
            continue
        if a in pts and b in pts:
            ax, ay = proj(*pts[a])
            bx, by = proj(*pts[b])
            segs.append({"x1": ax, "y1": ay, "x2": bx, "y2": by,
                         "mx": round((ax + bx) / 2, 1), "my": round((ay + by) / 2, 1),
                         "t": l.get("TravelTime")})
    return {"w": w, "h": h, "nodes": nodes, "segs": segs}


@app.get("/galaxy", response_class=HTMLResponse)
async def galaxy_page(request: Request):
    try:
        systems = await cached("systems", 86400, api.list_star_systems)
        links = await cached("syslinks", 86400, api.list_star_system_links)
    except PSSApiError:
        systems, links = [], []
    gmap = _galaxy_map(systems, links)
    lore = sorted(
        [{"title": s.get("StarSystemTitle", ""), "desc": clean_text(s.get("StarSystemDescription")),
          "sprite": s.get("IconSpriteId"), "req": clean_text(s.get("RequirementDescription"))}
         for s in systems if s.get("StarSystemTitle")],
        key=lambda s: s["title"])
    return render(request, "galaxy.html", gmap=gmap, lore=lore)


@app.get("/collections", response_class=HTMLResponse)
async def collections_page(request: Request):
    await data.ensure_loaded()
    colls = sorted(data.collections.values(), key=lambda c: c.get("CollectionName", ""))
    members = {c["CollectionDesignId"]: data.crew_in_collection(c["CollectionDesignId"])
               for c in colls}
    return render(request, "collections.html", collections=colls, members=members)


@app.get("/crew", response_class=HTMLResponse)
async def crew_list(request: Request, q: str = "", rarity: str = "", sort: str = "name"):
    await data.ensure_loaded()
    crew = list(data.characters.values())
    if q:
        crew = [c for c in crew if q.lower() in c.get("CharacterDesignName", "").lower()]
    if rarity:
        crew = [c for c in crew if c.get("Rarity") == rarity]
    sort_keys = {
        "name": lambda c: c.get("CharacterDesignName", ""),
        "hp": lambda c: -float(c.get("FinalHp", 0) or 0),
        "attack": lambda c: -float(c.get("FinalAttack", 0) or 0),
        "repair": lambda c: -float(c.get("FinalRepair", 0) or 0),
        "ability": lambda c: -float(c.get("SpecialAbilityFinalArgument", 0) or 0),
    }
    crew.sort(key=sort_keys.get(sort, sort_keys["name"]))
    rarities = sorted({c.get("Rarity", "") for c in data.characters.values()})
    return render(request, "crew_list.html", crew=crew[:200], total=len(crew),
                  q=q, rarity=rarity, sort=sort, rarities=rarities)


@app.get("/crew/{char_id}", response_class=HTMLResponse)
async def crew_detail(request: Request, char_id: int):
    await data.ensure_loaded()
    c = data.characters.get(char_id)
    if not c:
        raise HTTPException(404, "Crew not found")
    try:
        to_recipes = await cached(f"pto:{char_id}", 3600, lambda: api.prestige_to(char_id))
        from_recipes = await cached(f"pfrom:{char_id}", 3600, lambda: api.prestige_from(char_id))
    except PSSApiError:
        to_recipes, from_recipes = [], []
    collection = None
    if c.get("CollectionDesignId") not in (None, "", "0"):
        collection = data.collections.get(int(c["CollectionDesignId"]))

    # Stat progression table: exact at levels 1 and 40, interpolated between.
    def f(key: str) -> float:
        try:
            return float(c.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    progression = c.get("ProgressionType", "Linear")
    levels = [1, 10, 20, 30, 40]
    stat_rows = []
    for label, base_key, final_key in (
        ("HP", "Hp", "FinalHp"), ("Attack", "Attack", "FinalAttack"),
        ("Repair", "Repair", "FinalRepair"),
        ("Ability", "SpecialAbilityArgument", "SpecialAbilityFinalArgument"),
    ):
        base, final = f(base_key), f(final_key)
        if final <= 0:
            continue
        stat_rows.append({
            "label": label,
            "values": [num(round(interpolate_stat(base, final, lv, progression), 1))
                       for lv in levels],
        })
    event_sources = await _event_sources("character", char_id)
    return render(request, "crew_detail.html", c=c, collection=collection,
                  to_recipes=to_recipes, from_recipes=from_recipes,
                  char_name=data.char_name, levels=levels, stat_rows=stat_rows,
                  progression=progression, event_sources=event_sources)


@app.get("/items", response_class=HTMLResponse)
async def item_list(request: Request, q: str = "", type: str = "", rarity: str = ""):
    await data.ensure_loaded()
    items = list(data.items.values())
    if q:
        items = [i for i in items if q.lower() in i.get("ItemDesignName", "").lower()]
    if type:
        items = [i for i in items if i.get("ItemType") == type]
    if rarity:
        items = [i for i in items if i.get("Rarity") == rarity]
    items.sort(key=lambda i: i.get("ItemDesignName", ""))
    types = sorted({i.get("ItemType", "") for i in data.items.values()})
    rarities = sorted({i.get("Rarity", "") for i in data.items.values()})
    return render(request, "item_list.html", items=items[:200], total=len(items),
                  q=q, type=type, rarity=rarity, types=types, rarities=rarities)


def _price_chart(history: list[tuple[str, int]]) -> dict | None:
    """Precompute SVG geometry for the 30-day price line chart.

    Layout: 640x220 viewBox, 8px padding + room for y labels; the template
    renders a 2px line, recessive gridlines and per-point hover targets.
    """
    if len(history) < 2:
        return None
    w, h = 640, 220
    pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 28
    values = [v for _, v in history]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(history)

    def x(i: int) -> float:
        return pad_l + i * (w - pad_l - pad_r) / (n - 1)

    def y(v: float) -> float:
        return pad_t + (hi - v) * (h - pad_t - pad_b) / span

    points = [
        {"x": round(x(i), 1), "y": round(y(v), 1), "date": d[:10], "value": v}
        for i, (d, v) in enumerate(history)
    ]
    path = "M " + " L ".join(f"{p['x']},{p['y']}" for p in points)
    # 3 recessive horizontal gridlines: min, mid, max
    grid = [
        {"y": round(y(v), 1), "label": f"{v:,.0f}"}
        for v in (lo, (lo + hi) / 2, hi)
    ]
    latest = points[-1]
    # Direct label: above the point normally, below it when the point sits
    # near the top edge (otherwise the label would be clipped).
    label_y = latest["y"] + 22 if latest["y"] < pad_t + 18 else latest["y"] - 10
    return {"w": w, "h": h, "path": path, "points": points, "grid": grid,
            "latest": latest, "label_y": round(label_y, 1), "lo": lo, "hi": hi}


@app.get("/item/{item_id}", response_class=HTMLResponse)
async def item_detail(request: Request, item_id: int):
    await data.ensure_loaded()
    it = data.items.get(item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    try:
        history = await cached(f"price:{item_id}", 3600, lambda: api.price_history(item_id))
    except PSSApiError:
        history = []
    summary = None
    if len(history) >= 7:
        recent = [v for _, v in history[-7:]]
        older = [v for _, v in history[:-7]] or recent
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        drift = (avg_recent - avg_older) / avg_older * 100 if avg_older else 0
        trend = "rising" if drift > 5 else "falling" if drift < -5 else "stable"
        summary = {
            "lo": min(recent), "hi": max(recent),
            "trend": trend, "drift": round(drift),
        }
    recurrence = await asyncio.to_thread(_offer_recurrence, "Item", str(item_id))
    event_sources = await _event_sources("item", item_id)
    return render(request, "item_detail.html", it=it, history=history,
                  chart=_price_chart(history), summary=summary,
                  recurrence=recurrence, event_sources=event_sources,
                  items_table=data.items)


@app.get("/fleets", response_class=HTMLResponse)
async def fleets(request: Request):
    top = await cached("fleets100", 300, lambda: api.top_alliances(take=100))
    return render(request, "fleets.html", fleets=top)


@app.get("/fleet/{alliance_id}", response_class=HTMLResponse)
async def fleet_detail(request: Request, alliance_id: int):
    top = await cached("fleets100", 300, lambda: api.top_alliances(take=100))
    by_id = {int(a.get("AllianceId", 0) or 0): (i + 1, a) for i, a in enumerate(top)}
    hit = by_id.get(alliance_id)
    if not hit:
        raise HTTPException(404, "Fleet not in the current top 100")
    rank, a = hit
    return render(request, "fleet_detail.html", a=a, rank=rank)


def _fmt_dt(raw: str | None) -> str:
    dt = parse_pss_datetime(raw)
    return dt.strftime("%Y-%m-%d") if dt else "unknown"


@app.get("/players", response_class=HTMLResponse)
async def players(request: Request, q: str = ""):
    user = None
    error = None
    if q:
        try:
            users = await api.search_users(q)
            user = users[0] if users else None
            if user:
                seen = parse_pss_datetime(user.get("LastHeartBeatDate") or user.get("LastLoginDate"))
                user["_last_seen"] = seen.strftime("%Y-%m-%d %H:%M UTC") if seen else "unknown"
                user["_created"] = _fmt_dt(user.get("CreationDate"))
        except PSSApiError as exc:
            error = str(exc)
    return render(request, "players.html", q=q, user=user, error=error)


# --- prestige planner --------------------------------------------------------
MAX_ROSTER = 40


def _parse_roster(raw: str) -> list[int]:
    """Parse the roster query param into valid, deduped crew ids."""
    ids: list[int] = []
    for part in raw.split(","):
        # int() directly: str.isdigit() accepts Unicode digits (e.g. "²")
        # that int() rejects, which would crash here.
        try:
            cid = int(part.strip())
        except ValueError:
            continue
        if cid in data.characters and cid not in ids:
            ids.append(cid)
    return ids[:MAX_ROSTER]


def _combos_for_roster(roster: list[int],
                       recipes_by_crew: dict[int, list[dict[str, str]]]) -> list[dict]:
    """All prestige results attainable with pairs from the roster.

    ``recipes_by_crew[cid]`` holds PrestigeCharacterFrom(cid) rows; every row
    contains cid itself plus its partner. A combo is attainable when the
    partner is also in the roster. Deduped by (pair, target).
    """
    roster_set = set(roster)
    seen: set[tuple[frozenset[int], int]] = set()
    combos: list[dict] = []
    for cid in roster:
        for r in recipes_by_crew.get(cid, []):
            try:
                a = int(r.get("CharacterDesignId1", 0))
                b = int(r.get("CharacterDesignId2", 0))
                to = int(r.get("ToCharacterDesignId", 0))
            except (TypeError, ValueError):
                continue
            if a not in roster_set or b not in roster_set:
                continue
            key = (frozenset((a, b)), to)
            if key in seen:
                continue
            seen.add(key)
            combos.append({"a": a, "b": b, "to": to})
    return combos


RARITY_ORDER = {"Legendary": 0, "Special": 1, "Hero": 2, "Epic": 3,
                "Unique": 4, "Elite": 5, "Common": 6}


@app.get("/planner", response_class=HTMLResponse)
async def prestige_planner(request: Request, roster: str = "", q: str = ""):
    await data.ensure_loaded()
    roster_ids = _parse_roster(roster)
    roster_crew = [data.characters[cid] for cid in roster_ids]

    # Search box results (to add crew to the roster).
    matches = []
    if q:
        ql = q.lower()
        matches = [c for c in data.characters.values()
                   if ql in c.get("CharacterDesignName", "").lower()
                   and int(c["CharacterDesignId"]) not in roster_ids][:15]

    combos: list[dict] = []
    if len(roster_ids) >= 2:
        recipes_by_crew: dict[int, list[dict[str, str]]] = {}
        for cid in roster_ids:
            try:
                recipes_by_crew[cid] = await cached(
                    f"pfrom:{cid}", 3600, lambda cid=cid: api.prestige_from(cid))
            except PSSApiError:
                recipes_by_crew[cid] = []
        combos = _combos_for_roster(roster_ids, recipes_by_crew)
        # Enrich + sort by target rarity then name.
        for c in combos:
            target = data.characters.get(c["to"], {})
            c["target"] = target
            c["rarity_rank"] = RARITY_ORDER.get(target.get("Rarity", ""), 9)
        combos.sort(key=lambda c: (c["rarity_rank"],
                                   c["target"].get("CharacterDesignName", "")))

    roster_param = ",".join(str(i) for i in roster_ids)
    return render(request, "planner.html", roster_ids=roster_ids,
                  roster_crew=roster_crew, roster_param=roster_param,
                  q=q, matches=matches, combos=combos,
                  char=lambda cid: data.characters.get(cid, {}),
                  max_roster=MAX_ROSTER)


# --- JSON API ---------------------------------------------------------------
@app.get("/api/crew")
async def api_crew():
    await data.ensure_loaded()
    return JSONResponse(list(data.characters.values()))


@app.get("/api/items")
async def api_items():
    await data.ensure_loaded()
    return JSONResponse(list(data.items.values()))


@app.get("/api/daily")
async def api_daily():
    return JSONResponse(await cached("liveops", 300, api.today_liveops))


@app.get("/healthz")
async def healthz():
    return {"ok": True, "crew": len(data.characters), "items": len(data.items)}


# --- sprite proxy -------------------------------------------------------------
@app.get("/sprite/{file_id}.png")
async def sprite_file(file_id: int):
    """Serve a spritesheet, fetching from the game CDN once and disk-caching."""
    if not (0 < file_id < 10_000_000):
        raise HTTPException(404)
    path = os.path.join(SPRITE_CACHE_DIR, f"{file_id}.png")
    if not os.path.exists(path):
        os.makedirs(SPRITE_CACHE_DIR, exist_ok=True)
        if api._session is None or api._session.closed:
            await api.start()
        try:
            async with api._session.get(f"{SPRITE_UPSTREAM}/{file_id}.png") as resp:
                if resp.status != 200:
                    raise HTTPException(404, "Sprite sheet not found")
                content = await resp.read()
        except aiohttp.ClientError as exc:
            raise HTTPException(502, f"Upstream error: {exc}")
        tmp = f"{path}.tmp-{os.getpid()}"
        with open(tmp, "wb") as fh:
            fh.write(content)
        os.replace(tmp, path)
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})


# --- SEO ---------------------------------------------------------------------
@app.get("/robots.txt")
async def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(
        f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
    )


@app.get("/sitemap.xml")
async def sitemap(request: Request):
    await data.ensure_loaded()
    base = str(request.base_url).rstrip("/")
    urls = ["/", "/crew", "/items", "/rooms", "/ships", "/collections",
            "/fleets", "/players", "/planner", "/recruit", "/achievements", "/galaxy", "/events"]
    urls += [f"/crew/{cid}" for cid in data.characters]
    urls += [f"/item/{iid}" for iid in data.items]
    body = "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{body}</urlset>")
    return Response(content=xml, media_type="application/xml")
