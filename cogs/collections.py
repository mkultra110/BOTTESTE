"""Crew collection commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clamp, clean_text, rarity_icon

from ._autocomplete import suggest


class Collections(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _collection_ac(self, interaction: discord.Interaction, current: str):
        return await suggest(interaction, current, "suggest_collections")

    @app_commands.command(
        name="collection", description="Show a crew collection's bonus and members (or list all)."
    )
    @app_commands.describe(name="Collection name (leave empty to list all collections)")
    @app_commands.autocomplete(name=_collection_ac)
    async def collection(self, interaction: discord.Interaction, name: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        data = self.bot.data  # type: ignore[attr-defined]
        try:
            await data.ensure_loaded()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        if not data.collections:
            await interaction.followup.send("No collection data available.")
            return

        if not name:
            names = sorted(c.get("CollectionName", "?") for c in data.collections.values())
            embed = discord.Embed(
                title=f"🎖️ {len(names)} crew collections",
                description=clamp(", ".join(f"**{n}**" for n in names), 4096),
                color=config.BOT_COLOR,
            )
            embed.set_footer(text="Use /collection <name> for details.")
            await interaction.followup.send(embed=embed)
            return

        coll = data.find_collection(name)
        if coll is None:
            await interaction.followup.send(f"No collection found matching **{name}**.")
            return

        await interaction.followup.send(embed=self._collection_embed(data, coll))

    def _collection_embed(self, data, coll: dict[str, str]) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎖️ {coll.get('CollectionName', '?')}",
            description=clean_text(coll.get("CollectionDescription")),
            color=config.BOT_COLOR,
        )
        if coll.get("AbilityName"):
            embed.add_field(name="✨ Combo ability", value=coll["AbilityName"], inline=True)
        if coll.get("EnhancementType") and coll["EnhancementType"] != "None":
            embed.add_field(name="Bonus type", value=coll["EnhancementType"], inline=True)

        combo = f"{coll.get('MinCombo', '?')}–{coll.get('MaxCombo', '?')}"
        embed.add_field(name="Combo size", value=combo, inline=True)

        base = coll.get("BaseChance")
        step = coll.get("StepChance")
        if base and base != "0":
            chance = f"{base}%"
            if step and step != "0":
                chance += f" (+{step}%/crew)"
            embed.add_field(name="Trigger chance", value=chance, inline=True)

        members = sorted(
            data.crew_in_collection(coll["CollectionDesignId"]),
            key=lambda c: c.get("CharacterDesignName", ""),
        )
        if members:
            listing = ", ".join(
                f"{rarity_icon(m.get('Rarity', ''))} {m.get('CharacterDesignName', '?')}"
                for m in members[:40]
            )
            title = f"👥 Crew ({len(members)})"
            embed.add_field(name=title, value=clamp(listing), inline=False)

        embed.set_footer(text=f"Collection ID {coll.get('CollectionDesignId', '?')}")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Collections(bot))
