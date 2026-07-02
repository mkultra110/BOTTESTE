"""Ship room lookup command."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clamp, clean_text, num

from ._autocomplete import suggest


def _fmt_time(seconds: str | None) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "?"
    if s <= 0:
        return "—"
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m{sec:02d}s" if sec else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if m else f"{h}h"


class Rooms(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _room_ac(self, interaction: discord.Interaction, current: str):
        return await suggest(interaction, current, "suggest_rooms")

    @app_commands.command(name="room", description="Look up a ship room's stats across its levels.")
    @app_commands.describe(name="Room name (e.g. 'bridge', 'ion cannon', 'shield')")
    @app_commands.autocomplete(name=_room_ac)
    async def room(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        data = self.bot.data  # type: ignore[attr-defined]
        try:
            await data.ensure_loaded()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        rooms = data.find_rooms(name, limit=15)
        if not rooms:
            await interaction.followup.send(f"No room found matching **{name}**.")
            return

        # Group by room family (base name without level) using RoomType + short name.
        base = rooms[0]
        embed = discord.Embed(
            title=f"🛠️ {base.get('RoomName', '?')}",
            description=clamp(clean_text(base.get("RoomDescription")), 4096),
            color=config.BOT_COLOR,
        )
        embed.add_field(name="Type", value=base.get("RoomType", "?"), inline=True)
        if base.get("MinShipLevel"):
            embed.add_field(name="Min ship lvl", value=base["MinShipLevel"], inline=True)
        power = base.get("MaxSystemPower")
        if power and power != "0":
            embed.add_field(name="⚡ Power use", value=num(power), inline=True)
        gen = base.get("MaxPowerGenerated")
        if gen and gen != "0":
            embed.add_field(name="⚡ Power made", value=num(gen), inline=True)
        if base.get("Capacity") and base["Capacity"] != "0":
            embed.add_field(name="Capacity", value=num(base["Capacity"]), inline=True)
        # ReloadTime is stored in game ticks (40 ticks = 1 second).
        if base.get("ReloadTime") and base["ReloadTime"] != "0":
            try:
                reload_s = round(int(base["ReloadTime"]) / 40)
                embed.add_field(name="Reload", value=_fmt_time(str(reload_s)), inline=True)
            except (TypeError, ValueError):
                pass

        # List the level variants found.
        variants = [
            f"**{r.get('RoomShortName') or r.get('RoomName')}** "
            f"(lvl {r.get('MinShipLevel', '?')}, build {_fmt_time(r.get('ConstructionTime'))})"
            for r in rooms
        ]
        if len(variants) > 1:
            embed.add_field(name=f"Variants ({len(variants)})", value=clamp("\n".join(variants)), inline=False)

        embed.set_footer(text=f"Room ID {base.get('RoomDesignId', '?')}")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Rooms(bot))
