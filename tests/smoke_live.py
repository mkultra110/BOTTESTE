"""End-to-end smoke test against the LIVE Pixel Starships API.

Unlike the unit tests (which never touch the network), this exercises the data
path of every command so you can confirm the bot works before deploying:

    python tests/smoke_live.py

It does NOT connect to Discord — it only calls the PSS API through the same
client and cache the bot uses, and prints a PASS/FAIL line per feature.
Exit code is non-zero if any check fails.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pss.api import PSSApi
from pss.cache import GameData
from pss.formatting import ability_name, num, sparkline


class Check:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, name: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
        if not condition:
            self.failures.append(name)


async def main() -> int:
    c = Check()
    api = PSSApi("api.pixelstarships.com", "en")
    await api.start()
    data = GameData(api)
    try:
        await data.ensure_loaded()
        c.ok("game data loads", len(data.characters) > 100 and len(data.items) > 500,
             f"{len(data.characters)} crew, {len(data.items)} items, "
             f"{len(data.rooms)} rooms, {len(data.collections)} collections")

        # /player
        users = await api.search_users("rocky")
        c.ok("/player search", bool(users), f"{len(users)} result(s)")

        # /fleet-top
        fleets = await api.top_alliances(take=5)
        c.ok("/fleet-top", len(fleets) == 5 and fleets[0].get("DivisionDesignId") is not None,
             fleets[0].get("AllianceName") if fleets else "none")

        # /crew + decimal stats
        laura = data.find_character("laura")
        c.ok("/crew lookup + decimal stat", laura is not None and "." in laura.get("FinalAttack", ""),
             f"Laura ATK={laura.get('FinalAttack') if laura else '?'} -> {num(laura['FinalAttack']) if laura else '?'}")

        # /crew-top
        ranked = sorted(data.characters.values(),
                        key=lambda x: float(x.get("FinalHp", 0) or 0), reverse=True)
        c.ok("/crew-top ranking", ranked and float(ranked[0].get("FinalHp", 0)) > 0,
             f"top HP: {ranked[0].get('CharacterDesignName')}")

        # ability name mapping
        c.ok("ability name map", ability_name("DeductReload") == "System Hack")

        # /prestige
        xin = data.find_character("xin")
        combos = await api.prestige_from(int(xin["CharacterDesignId"])) if xin else []
        c.ok("/prestige combos", len(combos) > 0, f"{len(combos)} combos for Xin")

        # /collection
        coll = data.find_collection("cosmic")
        members = data.crew_in_collection(coll["CollectionDesignId"]) if coll else []
        c.ok("/collection + members", coll is not None and len(members) > 0,
             f"{coll.get('CollectionName') if coll else '?'}: {len(members)} crew")

        # /item + /price
        item = data.find_item("android")
        c.ok("/item lookup", item is not None, item.get("ItemDesignName") if item else "none")
        pts = await api.price_history(600)
        c.ok("/price history", len(pts) > 0, f"{len(pts)} points, spark={sparkline([v for _, v in pts])}")

        # /room + reload conversion
        rooms = data.find_rooms("ion cannon")
        base = rooms[0] if rooms else {}
        c.ok("/room natural order", [r["RoomName"] for r in rooms][:3] ==
             ["Ion Cannon Lv1", "Ion Cannon Lv2", "Ion Cannon Lv3"],
             ", ".join(r["RoomName"] for r in rooms[:3]))

        # /daily
        ops = await api.today_liveops()
        c.ok("/daily liveops", bool(ops.get("News")), f"reward={ops.get('DailyRewardType')}")

    finally:
        await api.close()

    print()
    if c.failures:
        print(f"❌ {len(c.failures)} check(s) failed: {', '.join(c.failures)}")
        return 1
    print("✅ All live smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
