"""Fleet (alliance) commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clean_text, num


class Fleets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="fleet-top", description="Show the top fleets by trophies.")
    @app_commands.describe(count="How many fleets to show (1-25, default 10)")
    async def fleet_top(self, interaction: discord.Interaction, count: int = 10) -> None:
        await interaction.response.defer(thinking=True)
        api = self.bot.api  # type: ignore[attr-defined]
        count = max(1, min(count, 25))
        try:
            alliances = await api.top_alliances(take=count)
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        if not alliances:
            await interaction.followup.send("No fleet data available right now.")
            return

        divisions = {1: "A", 2: "B", 3: "C", 4: "D"}
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        lines = []
        for i, a in enumerate(alliances[:count]):
            rank = medals.get(i, f"`#{i + 1}`")
            name = clean_text(a.get("AllianceName")) or "?"
            trophy = num(a.get("Trophy"))
            members = a.get("NumberOfMembers")
            member_str = f" • 👥 {members}" if members else ""
            try:
                div = divisions.get(int(a.get("DivisionDesignId", 0)))
            except (TypeError, ValueError):
                div = None
            div_str = f" • Div {div}" if div else ""
            score = a.get("Score")
            score_str = f" • ⭐ {num(score)}" if score and score != "0" else ""
            lines.append(f"{rank} **{name}** — 🏆 {trophy}{member_str}{score_str}{div_str}")

        embed = discord.Embed(
            title="🚀 Top fleets",
            description="\n".join(lines),
            color=config.BOT_COLOR,
        )
        embed.set_footer(text="Ranked by trophies • data from the public PSS API")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Fleets(bot))
