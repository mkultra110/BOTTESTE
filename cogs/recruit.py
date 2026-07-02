"""Recruit / draw odds command."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clean_text, num

# PSS crew rarity is a 0-indexed scale on draw designs.
RARITY_SCALE = ["Common", "Elite", "Unique", "Epic", "Hero", "Legendary", "Special"]


def _rarity(idx: str | None) -> str:
    try:
        return RARITY_SCALE[int(idx)]
    except (TypeError, ValueError, IndexError):
        return "?"


def _cost(raw: str | None) -> str:
    """Format a 'kind:amount' cost like 'starbux:100' -> '100 Starbux'."""
    if not raw or ":" not in raw:
        return raw or "?"
    kind, _, amount = raw.partition(":")
    return f"{num(amount)} {kind.capitalize()}"


class Recruit(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="draws", description="Recruit (draw) options: cost, rarity range and pity.")
    async def draws(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        api = self.bot.api  # type: ignore[attr-defined]
        try:
            draws = await api.list_draw_designs()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        if not draws:
            await interaction.followup.send("No recruit data available.")
            return

        draws.sort(key=lambda d: int(d.get("OrderIndex", 0) or 0))
        embed = discord.Embed(
            title="🎰 Crew recruitment",
            description="Draw options, base cost and rarity range.",
            color=config.BOT_COLOR,
        )
        for d in draws:
            lo, hi = _rarity(d.get("MinCrewRarity")), _rarity(d.get("MaxCrewRarity"))
            rarity_range = lo if lo == hi else f"{lo} → {hi}"
            lines = [
                f"**Cost:** {_cost(d.get('Cost'))}",
                f"**Rarity:** {rarity_range}",
            ]
            inc = d.get("CostPercentageIncrease")
            if inc and inc != "0":
                lines.append(f"**Cost rises:** +{inc}% per draw")
            pity = d.get("GuaranteedHeroicDraws")
            if pity and pity != "0":
                lines.append(f"**Pity:** guaranteed Hero every {pity} draws")
            desc = clean_text(d.get("DrawDescription"))
            if desc:
                lines.append(f"_{desc}_")
            embed.add_field(name=d.get("DrawName", "?"), value="\n".join(lines), inline=False)

        embed.set_footer(text="Recruitment odds • data from the public PSS API")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Recruit(bot))
