"""General / meta commands: /help, /ping, /about."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

import config


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check that the bot is alive.")
    async def ping(self, interaction: discord.Interaction) -> None:
        start = time.perf_counter()
        await interaction.response.defer(thinking=True, ephemeral=True)
        elapsed = (time.perf_counter() - start) * 1000
        ws = self.bot.latency * 1000
        await interaction.followup.send(
            f"🏓 Pong! Gateway latency **{ws:.0f} ms**, response **{elapsed:.0f} ms**.",
            ephemeral=True,
        )

    @app_commands.command(name="about", description="About this bot and its data source.")
    async def about(self, interaction: discord.Interaction) -> None:
        api = self.bot.api  # type: ignore[attr-defined]
        embed = discord.Embed(
            title="Pixel Starships Bot",
            description=(
                "An unofficial companion bot for **Pixel Starships** by Savy Soda.\n"
                "Data comes from the public PSS API. Not affiliated with or "
                "endorsed by Savy Soda."
            ),
            color=config.BOT_COLOR,
        )
        embed.add_field(name="Language", value=config.PSS_LANGUAGE, inline=True)
        embed.add_field(
            name="Authenticated features",
            value="✅ enabled" if getattr(api, "has_auth", False) else "❌ disabled",
            inline=True,
        )
        embed.set_footer(text="Type /help to see all commands.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="List everything this bot can do.")
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        api = self.bot.api  # type: ignore[attr-defined]
        embed = discord.Embed(
            title="📖 Command reference",
            color=config.BOT_COLOR,
            description="Everything the Pixel Starships bot can do:",
        )
        embed.add_field(
            name="👤 Players",
            value="`/player <name>` — search a player and show trophies, fleet, last seen.",
            inline=False,
        )
        embed.add_field(
            name="🚀 Fleets",
            value="`/fleet-top [count]` — top fleets by trophies.",
            inline=False,
        )
        embed.add_field(
            name="🧑‍🚀 Crew",
            value=(
                "`/crew <name>` — crew stats, ability and rarity.\n"
                "`/prestige <crew1> <crew2>` — what two crew prestige into.\n"
                "`/prestige-recipes <crew>` — all ways to obtain a crew."
            ),
            inline=False,
        )
        embed.add_field(
            name="📦 Items",
            value="`/item <name>` — item details and market price.",
            inline=False,
        )
        embed.add_field(
            name="📅 Daily",
            value="`/daily` — today's offers, sale, daily reward and news.",
            inline=False,
        )
        if getattr(api, "has_auth", False):
            embed.add_field(
                name="🏆 Rankings (authenticated)",
                value="`/top-players [count]` — global player leaderboard.",
                inline=False,
            )
        embed.set_footer(text="Unofficial • data from the public PSS API")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
