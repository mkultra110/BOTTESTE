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
