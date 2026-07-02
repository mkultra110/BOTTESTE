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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
_live_cache: dict[str, tuple[float, object]] = {}


async def cached(key: str, ttl: float, factory):
    now = time.monotonic()
    hit = _live_cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = await factory()
    _live_cache[key] = (now, value)
    return value


# --- daily archive (liveops + fleet standings) ------------------------------
# History cannot be backfilled, so snapshots run from day one. Stored as
# JSON-lines, one file per dataset, deduped by UTC date.
ARCHIVE_DIR = os.environ.get("PSS_ARCHIVE_DIR", os.path.join(os.getcwd(), "data", "archive"))


def _archive_has(path: str, date: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as fh:
            tail = fh.read()[-4096:].decode(errors="ignore")
        return f'"date": "{date}"' in tail or f'"date":"{date}"' in tail
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

templates = Jinja2Templates(directory=os.path.join(WEB_DIR, "templates"))
templates.env.filters["num"] = num
templates.env.filters["clean"] = clean_text
templates.env.filters["rarity_icon"] = rarity_icon
templates.env.filters["ability"] = ability_name
templates.env.filters["slots"] = equipment_slots
templates.env.globals["now"] = time.time


def render(request: Request, template: str, **ctx) -> HTMLResponse:
    # Freshness is a product feature: every page shows how old the data is.
    age_min = int((time.monotonic() - data._loaded_at) / 60) if data._loaded_at else None
    ctx.setdefault("data_age_min", age_min)
    return templates.TemplateResponse(request, template, ctx)


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
    return render(request, "home.html", ops=ops, fleets=fleets, featured=featured,
                  sale_item=sale_item, news=clean_text(ops.get("News")),
                  tournament=tournament_info())


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
    return render(request, "crew_detail.html", c=c, collection=collection,
                  to_recipes=to_recipes, from_recipes=from_recipes,
                  char_name=data.char_name)


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
    return render(request, "item_detail.html", it=it, history=history,
                  chart=_price_chart(history), summary=summary,
                  items_table=data.items)


@app.get("/fleets", response_class=HTMLResponse)
async def fleets(request: Request):
    top = await cached("fleets100", 300, lambda: api.top_alliances(take=100))
    return render(request, "fleets.html", fleets=top)


@app.get("/players", response_class=HTMLResponse)
async def players(request: Request, q: str = ""):
    user = None
    error = None
    if q:
        try:
            users = await api.search_users(q)
            user = users[0] if users else None
            if user:
                dt = parse_pss_datetime(user.get("LastHeartBeatDate") or user.get("LastLoginDate"))
                user["_last_seen"] = dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "unknown"
        except PSSApiError as exc:
            error = str(exc)
    return render(request, "players.html", q=q, user=user, error=error)


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
