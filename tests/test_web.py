"""Unit tests for pure web helpers (no server, no network)."""
from datetime import datetime, timezone

import web.app as webapp


def test_tournament_info_live_last_week():
    # 28 July 2026: July has 31 days, finals run 25–31 -> live.
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    info = webapp.tournament_info(now)
    assert info["live"] is True
    assert "LIVE" in info["label"]


def test_tournament_info_before_finals():
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    info = webapp.tournament_info(now)
    assert info["live"] is False
    assert "in" in info["label"]


def test_tournament_info_after_finals_rolls_to_next_month():
    # 31 Dec 2026 23:59:59 is the end; 1 Jan should roll to January finals.
    now = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    info = webapp.tournament_info(now)
    assert info["live"] is False


def test_price_chart_geometry():
    history = [("2026-06-0%d" % (i + 1), 100 + i * 10) for i in range(5)]
    chart = webapp._price_chart(history)
    assert chart is not None
    assert len(chart["points"]) == 5
    assert chart["latest"]["value"] == 140
    assert chart["path"].startswith("M ")


def test_price_chart_needs_two_points():
    assert webapp._price_chart([]) is None
    assert webapp._price_chart([("2026-06-01", 100)]) is None


def test_percentile_top():
    peers = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert webapp._percentile_top(peers, 10.0) == 1   # best -> top 1%
    assert webapp._percentile_top(peers, 5.0) == 50   # median
    assert webapp._percentile_top(peers, 0.5) == 100  # worst
    assert webapp._percentile_top([], 5.0) == 100     # no peers


def test_parse_roster_validates_and_dedupes():
    webapp.data.characters = {1: {"CharacterDesignId": "1"}, 2: {"CharacterDesignId": "2"}}
    assert webapp._parse_roster("1,2,2,abc,999") == [1, 2]
    assert webapp._parse_roster("") == []
    webapp.data.characters = {}


def test_combos_for_roster_requires_both_partners():
    recipes = {
        1: [{"CharacterDesignId1": "1", "CharacterDesignId2": "2", "ToCharacterDesignId": "10"},
            {"CharacterDesignId1": "1", "CharacterDesignId2": "3", "ToCharacterDesignId": "11"}],
        2: [{"CharacterDesignId1": "1", "CharacterDesignId2": "2", "ToCharacterDesignId": "10"}],
    }
    combos = webapp._combos_for_roster([1, 2], recipes)
    # 1+3 is impossible (3 not owned); 1+2 dedupes to a single combo.
    assert len(combos) == 1
    assert combos[0] == {"a": 1, "b": 2, "to": 10}


def test_crew_verdict_uses_same_rarity_peers():
    webapp.data.characters = {
        1: {"CharacterDesignId": "1", "Rarity": "Hero", "FinalAttack": "10",
            "FinalHp": "5", "FinalRepair": "1", "SpecialAbilityFinalArgument": "0"},
        2: {"CharacterDesignId": "2", "Rarity": "Hero", "FinalAttack": "2",
            "FinalHp": "9", "FinalRepair": "2", "SpecialAbilityFinalArgument": "0"},
        3: {"CharacterDesignId": "3", "Rarity": "Common", "FinalAttack": "99",
            "FinalHp": "99", "FinalRepair": "99", "SpecialAbilityFinalArgument": "0"},
    }
    v = webapp._crew_verdict(webapp.data.characters[1])
    assert v["peer_count"] == 2          # commons excluded
    assert v["best"]["label"] == "ATK"   # attack is its best stat
    assert v["best"]["top"] == 1
    webapp.data.characters = {}
