"""Unit tests for the item-ref / cargo / sale parsing in the cogs."""
import asyncio
import types

from cogs.daily import Daily
from cogs.items import Items
from pss.cache import GameData
from tests.test_cache import FakeApi, CHARS, COLLECTIONS


ITEMS = [
    {"ItemDesignId": "101", "ItemDesignName": "Titanium"},
    {"ItemDesignId": "102", "ItemDesignName": "Silicon"},
    {"ItemDesignId": "836", "ItemDesignName": "Firework Mine"},
    {"ItemDesignId": "1187", "ItemDesignName": "Cooler Box"},
]


def build_data() -> GameData:
    data = GameData(FakeApi(CHARS, ITEMS, [], COLLECTIONS))
    asyncio.run(data.ensure_loaded(force=True))
    return data


def fake_bot():
    return types.SimpleNamespace(data=build_data())


def test_item_refs_plain_and_kinded():
    cog = Items(fake_bot())
    # plain "idxqty"
    assert cog._item_refs("101x5|102x12") == ["5× Titanium", "12× Silicon"]
    # "kind:idxqty"
    assert cog._item_refs("item:101x6|item:102x12") == ["6× Titanium", "12× Silicon"]
    # unknown id keeps a placeholder
    assert cog._item_refs("9999x1") == ["1× #9999"]


def test_cargo_pairs_items_with_prices():
    cog = Daily(fake_bot())
    out = cog._cargo(cog.bot.data, "836x1", "starbux:100")
    assert out == "1× Firework Mine — 100 starbux"


def test_cargo_multiple():
    cog = Daily(fake_bot())
    out = cog._cargo(cog.bot.data, "101x2|102x3", "starbux:50|gas:5")
    assert "2× Titanium — 50 starbux" in out
    assert "3× Silicon — 5 gas" in out


def test_cargo_empty():
    cog = Daily(fake_bot())
    assert cog._cargo(cog.bot.data, None, None) == ""


def test_sale_price_parses_usd():
    cog = Daily(fake_bot())
    assert cog._sale_price("item:1187x[USD/2]") == "USD 2"
    assert cog._sale_price("no-brackets") == ""
    assert cog._sale_price(None) == ""


def test_resolve_bonus_and_item():
    cog = Daily(fake_bot())
    assert cog._resolve(cog.bot.data, "Bonus", "50") == "+50% bonus"
    assert cog._resolve(cog.bot.data, "Item", "836") == "Firework Mine"
    assert cog._resolve(cog.bot.data, "FleetGift", "1187") == "Cooler Box"


def test_friendly_type():
    cog = Daily(fake_bot())
    assert cog._friendly_type("FleetGift") == "Fleet gift"
    assert cog._friendly_type("Whatever") == "Whatever"
