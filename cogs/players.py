"""Player lookup commands."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import num, relative_time

log = logging.getLogger("cogs.players")


class Players(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="player", description="Search a Pixel Starships player by name.")
    @app_commands.describe(name="Player name (or the start of it)")
    async def player(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        api = self.bot.api  # type: ignore[attr-defined]
        try:
            users = await api.search_users(name)
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        if not users:
            await interaction.followup.send(f"No player found matching **{name}**.")
            return

        # Exact (case-insensitive) match wins; else show the top results.
        exact = [u for u in users if u.get("Name", "").lower() == name.lower()]
        if len(exact) == 1:
            await interaction.followup.send(embed=self._player_embed(exact[0]))
            return
        if len(users) == 1:
            await interaction.followup.send(embed=self._player_embed(users[0]))
            return

        # Multiple matches: list them.
        users = sorted(users, key=lambda u: int(u.get("Trophy", 0) or 0), reverse=True)[:12]
        embed = discord.Embed(
            title=f"🔎 {len(users)} players matching “{name}”",
            color=config.BOT_COLOR,
            description="\n".join(
                f"**{u.get('Name', '?')}** — 🏆 {num(u.get('Trophy'))}"
                + (f" • {u.get('AllianceName')}" if u.get("AllianceName") else "")
                for u in users
            ),
        )
        embed.set_footer(text="Refine your search for an exact profile.")
        await interaction.followup.send(embed=embed)

    def _player_embed(self, u: dict[str, str]) -> discord.Embed:
        name = u.get("Name", "Unknown")
        embed = discord.Embed(title=f"👤 {name}", color=config.BOT_COLOR)
        embed.add_field(name="🏆 Trophies", value=num(u.get("Trophy")), inline=True)

        alliance = u.get("AllianceName")
        if alliance:
            embed.add_field(name="🚀 Fleet", value=alliance, inline=True)
        else:
            membership = u.get("AllianceMembership", "None")
            embed.add_field(
                name="🚀 Fleet",
                value="No fleet" if membership in ("None", "") else membership,
                inline=True,
            )

        if u.get("PVPAttackWins") is not None:
            wins = num(u.get("PVPAttackWins"))
            losses = num(u.get("PVPAttackLosses"))
            embed.add_field(name="⚔️ Attacks W/L", value=f"{wins} / {losses}", inline=True)

        last_seen = u.get("LastHeartBeatDate") or u.get("LastLoginDate") or u.get("LastAlertDate")
        if last_seen:
            embed.add_field(name="🕒 Last seen", value=relative_time(last_seen), inline=True)

        if u.get("CrewDonated") is not None:
            embed.add_field(
                name="🤝 Crew donated / received",
                value=f"{num(u.get('CrewDonated'))} / {num(u.get('CrewReceived'))}",
                inline=True,
            )

        race = u.get("RaceType")
        if race and race != "Unknown":
            embed.add_field(name="🧬 Race", value=race, inline=True)

        embed.set_footer(text=f"Player ID {u.get('Id', '?')}")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Players(bot))
