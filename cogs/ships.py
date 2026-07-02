"""Ship hull lookup command."""
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


class Ships(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _ship_ac(self, interaction: discord.Interaction, current: str):
        return await suggest(interaction, current, "suggest_ships")

    @app_commands.command(name="ship", description="Look up a player ship hull's stats.")
    @app_commands.describe(name="Ship hull name (e.g. 'crab', 'nightmare')")
    @app_commands.autocomplete(name=_ship_ac)
    async def ship(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        data = self.bot.data  # type: ignore[attr-defined]
        try:
            await data.ensure_loaded()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        ship = data.find_ship(name)
        if ship is None:
            await interaction.followup.send(f"No player ship found matching **{name}**.")
            return

        embed = discord.Embed(
            title=f"🚀 {ship.get('ShipDesignName', '?')}",
            description=clamp(clean_text(ship.get("ShipDescription")), 4096),
            color=config.BOT_COLOR,
        )
        if ship.get("ShipLevel"):
            embed.add_field(name="Level", value=ship["ShipLevel"], inline=True)
        if ship.get("Hp") and ship["Hp"] != "0":
            embed.add_field(name="❤️ Hull HP", value=num(ship["Hp"]), inline=True)
        rows, cols = ship.get("Rows"), ship.get("Columns")
        if rows and cols:
            embed.add_field(name="Grid", value=f"{rows} × {cols}", inline=True)
        if ship.get("RepairTime") and ship["RepairTime"] != "0":
            embed.add_field(name="🔧 Repair/tile", value=_fmt_time(ship["RepairTime"]), inline=True)

        costs = []
        for key, label in (("MineralCost", "Mineral"), ("StarbuxCost", "Starbux")):
            v = ship.get(key)
            if v and v != "0":
                costs.append(f"{num(v)} {label}")
        if costs:
            embed.add_field(name="💰 Upgrade cost", value=", ".join(costs), inline=True)
        if ship.get("MaxDsp") and ship["MaxDsp"] != "0":
            embed.add_field(name="Max power (DSP)", value=num(ship["MaxDsp"]), inline=True)

        embed.set_footer(text=f"Ship ID {ship.get('ShipDesignId', '?')}")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ships(bot))
