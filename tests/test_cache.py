"""Unit tests for pss.cache — indexing and lookups with fixture data."""
import asyncio

from pss.cache import GameData, _norm


class FakeApi:
    """Stand-in for PSSApi returning canned design rows."""

    def __init__(self, chars, items, rooms, collections):
        self._chars, self._items = chars, items
        self._rooms, self._collections = rooms, collections

    async def list_character_designs(self):
        return self._chars

    async def list_item_designs(self):
        return self._items

    async def list_room_designs(self):
        return self._rooms

    async def list_collection_designs(self):
        return self._collections


CHARS = [
    {"CharacterDesignId": "3", "CharacterDesignName": "Michelle", "Rarity": "Special", "CollectionDesignId": "5"},
    {"CharacterDesignId": "25", "CharacterDesignName": "Michelle", "Rarity": "Common", "CollectionDesignId": "0"},
    {"CharacterDesignId": "55", "CharacterDesignName": "Ai-Ling", "Rarity": "Hero", "CollectionDesignId": "5"},
    {"CharacterDesignId": "99", "CharacterDesignName": "D.R.A.G.O.N", "Rarity": "Legendary"},
]
ITEMS = [
    {"ItemDesignId": "2", "ItemDesignName": "Gas"},
    {"ItemDesignId": "101", "ItemDesignName": "Android Defence AI"},
]
ROOMS = [
    {"RoomDesignId": "1", "RoomName": "Bridge Lv1", "MinShipLevel": "1"},
    {"RoomDesignId": "2", "RoomName": "Armor Lv2", "MinShipLevel": "2"},
    {"RoomDesignId": "10", "RoomName": "Armor Lv10", "MinShipLevel": "10"},
    {"RoomDesignId": "3", "RoomName": "Armor Lv1", "MinShipLevel": "1"},
]
COLLECTIONS = [{"CollectionDesignId": "5", "CollectionName": "Cosmic Crusaders"}]


def build() -> GameData:
    api = FakeApi(CHARS, ITEMS, ROOMS, COLLECTIONS)
    data = GameData(api)
    asyncio.run(data.ensure_loaded(force=True))
    return data


def test_loads_all_catalogues():
    data = build()
    assert len(data.characters) == 4
    assert len(data.items) == 2
    assert len(data.rooms) == 4
    assert len(data.collections) == 1


def test_duplicate_names_both_reachable():
    data = build()
    matches = data.find_characters("michelle")
    ids = {m["CharacterDesignId"] for m in matches}
    assert ids == {"3", "25"}, "both Michelles must be findable"


def test_find_character_exact_and_fuzzy():
    data = build()
    assert data.find_character("Ai-Ling")["CharacterDesignId"] == "55"
    # normalization drops punctuation
    assert data.find_character("dragon")["CharacterDesignId"] == "99"
    assert data.find_character("nonexistent") is None


def test_find_item():
    data = build()
    assert data.find_item("gas")["ItemDesignId"] == "2"
    assert data.find_item("android")["ItemDesignId"] == "101"


def test_collection_lookup_and_members():
    data = build()
    assert data.collection_name("5") == "Cosmic Crusaders"
    assert data.collection_name("999") == "#999"
    members = data.crew_in_collection("5")
    ids = {m["CharacterDesignId"] for m in members}
    assert ids == {"3", "55"}


def test_char_name_fallback():
    data = build()
    assert data.char_name("55") == "Ai-Ling"
    assert data.char_name("0") == "#0"


def test_norm():
    assert _norm("Katie-8 'Hammerhead'") == "katie8hammerhead"
    assert _norm("D.R.A.G.O.N") == "dragon"


def test_suggest_characters_prefix_and_substring():
    data = build()
    # prefix match
    s = data.suggest_characters("ai")
    assert "Ai-Ling" in s
    # substring / dedup: both Michelles share a name -> one entry
    s2 = data.suggest_characters("michelle")
    assert s2.count("Michelle") == 1
    # empty query returns some names, capped at 25
    assert 0 < len(data.suggest_characters("")) <= 25


def test_suggest_collections_and_items():
    data = build()
    assert "Cosmic Crusaders" in data.suggest_collections("cosmic")
    assert "Gas" in data.suggest_items("gas")


def test_find_rooms_natural_level_order():
    data = build()
    rooms = data.find_rooms("armor")
    names = [r["RoomName"] for r in rooms]
    # Lv1 before Lv2 before Lv10 (a plain string sort would put Lv10 second)
    assert names == ["Armor Lv1", "Armor Lv2", "Armor Lv10"], names
