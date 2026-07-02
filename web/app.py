"""Pixel Starships community website.

FastAPI + Jinja2, server-rendered. Reuses the same verified PSS API client
and design-data cache as the Discord bot (read-only, anonymous endpoints).

Run locally:
    uvicorn web.app:app --reload
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await api.start()
    try:
        await data.ensure_loaded()
    except Exception as exc:  # pragma: no cover - non fatal, retried on demand
        log.warning("Initial data load failed: %s", exc)
    yield
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
                  sale_item=sale_item, news=clean_text(ops.get("News")))


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
    return render(request, "item_detail.html", it=it, history=history,
                  chart=_price_chart(history), items_table=data.items)


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
