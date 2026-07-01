"""Unit tests for pss.formatting — pure logic, no network."""
from pss.formatting import (
    ability_name,
    clamp,
    clean_text,
    equipment_slots,
    num,
    parse_pss_datetime,
    rarity_icon,
    sparkline,
)


def test_num_preserves_decimals():
    assert num("1.9") == "1.9"
    assert num("1.70") == "1.7"
    assert num("8.5") == "8.5"


def test_num_formats_integers_with_separators():
    assert num("1000") == "1,000"
    assert num(1234567) == "1,234,567"
    assert num("5") == "5"


def test_num_handles_bad_values():
    assert num(None) == "?"
    assert num("") == "?"
    assert num("abc") == "abc"


def test_parse_pss_datetime_rejects_sentinels():
    assert parse_pss_datetime("1900-01-01T00:00:00") is None
    assert parse_pss_datetime("0001-01-01T00:00:00") is None
    assert parse_pss_datetime("2000-01-01T00:00:00") is None
    assert parse_pss_datetime("2001-01-01T00:00:00") is None


def test_parse_pss_datetime_accepts_real_dates():
    dt = parse_pss_datetime("2026-07-01T12:30:00")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 7


def test_parse_pss_datetime_strips_fractions_and_z():
    assert parse_pss_datetime("2026-07-01T12:30:00.1234567Z") is not None
    assert parse_pss_datetime(None) is None
    assert parse_pss_datetime("garbage") is None


def test_ability_name_maps_enums():
    assert ability_name("DeductReload") == "System Hack"
    assert ability_name("HealSelfHp") == "First Aid"
    assert ability_name("None") == ""
    assert ability_name("") == ""
    # Unknown enum falls back to the raw value.
    assert ability_name("SomethingNew") == "SomethingNew"


def test_equipment_slots_decodes_bits():
    assert equipment_slots("62") == "Body, Leg, Weapon, Accessory, Pet"
    assert equipment_slots("1") == "Head"
    assert equipment_slots("0") == ""
    assert equipment_slots(None) == ""
    assert equipment_slots("notanint") == ""


def test_clean_text_strips_markup():
    raw = "&lt;color=#FFD700&gt;Gold&lt;/color&gt;%0aline2"
    assert clean_text(raw) == "Gold\nline2"
    assert clean_text(None) == ""
    assert clean_text("<size=50>Big</size>") == "Big"


def test_clamp_truncates_with_ellipsis():
    assert clamp("short", 10) == "short"
    out = clamp("x" * 2000, 100)
    assert len(out) <= 100
    assert out.endswith("…")


def test_sparkline():
    assert sparkline([]) == ""
    # flat series -> all lowest block
    assert sparkline([5, 5, 5]) == "▁▁▁"
    out = sparkline([1, 2, 3, 4, 5])
    assert len(out) == 5
    assert out[0] == "▁" and out[-1] == "█"  # min and max map to ends


def test_rarity_icon_has_all_known_rarities():
    for r in ("Common", "Elite", "Unique", "Epic", "Hero", "Special", "Legendary"):
        assert rarity_icon(r)  # non-empty
    assert rarity_icon("Unknown") == "⭐"  # fallback
