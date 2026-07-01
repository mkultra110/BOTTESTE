"""Crew (character) commands: info, prestige combos and recipes."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clean_text, num, rarity_icon


class Crew(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _data(self):
        data = self.bot.data  # type: ignore[attr-defined]
        await data.ensure_loaded()
        return data

    @app_commands.command(name="crew", description="Look up a crew member's stats and ability.")
    @app_commands.describe(name="Crew name (or part of it)")
    async def crew(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = await self._data()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        char = data.find_character(name)
        if char is None:
            suggestions = data.find_characters(name, limit=8)
            if suggestions:
                names = ", ".join(f"**{c['CharacterDesignName']}**" for c in suggestions)
                await interaction.followup.send(
                    f"No exact match for “{name}”. Did you mean: {names}?"
                )
            else:
                await interaction.followup.send(f"No crew found matching **{name}**.")
            return

        await interaction.followup.send(embed=self._crew_embed(char))

    def _crew_embed(self, c: dict[str, str]) -> discord.Embed:
        rarity = c.get("Rarity", "Common")
        embed = discord.Embed(
            title=f"{rarity_icon(rarity)} {c.get('CharacterDesignName', '?')}",
            description=clean_text(c.get("CharacterDesignDescription")),
            color=config.BOT_COLOR,
        )
        embed.add_field(name="Rarity", value=rarity, inline=True)
        if c.get("Gender") or c.get("GenderType"):
            embed.add_field(name="Gender", value=c.get("GenderType", c.get("Gender", "?")), inline=True)
        if c.get("SpecialAbilityType") and c["SpecialAbilityType"] != "None":
            ability = c["SpecialAbilityType"]
            arg = c.get("SpecialAbilityFinalArgument") or c.get("SpecialAbilityArgument")
            embed.add_field(
                name="✨ Ability",
                value=f"{ability}" + (f" ({num(arg)})" if arg else ""),
                inline=True,
            )

        stats = [
            ("❤️ HP", "FinalHp"),
            ("⚔️ Attack", "FinalAttack"),
            ("🔧 Repair", "FinalRepair"),
            ("🛠️ Engine", "FinalEngine"),
            ("🔬 Science", "FinalScience"),
            ("🎯 Weapon", "FinalWeapon"),
            ("🚀 Pilot", "FinalPilot"),
            ("🧪 Research", "FinalResearch"),
        ]
        stat_lines = [
            f"{label}: **{num(c[key])}**" for label, key in stats if c.get(key) not in (None, "")
        ]
        if stat_lines:
            # two columns
            half = (len(stat_lines) + 1) // 2
            embed.add_field(name="Max stats", value="\n".join(stat_lines[:half]), inline=True)
            if stat_lines[half:]:
                embed.add_field(name="​", value="\n".join(stat_lines[half:]), inline=True)

        collection = c.get("CollectionDesignId")
        if collection and collection not in ("0", ""):
            embed.add_field(name="Collection", value=f"#{collection}", inline=True)

        embed.set_footer(text=f"Crew ID {c.get('CharacterDesignId', '?')}")
        return embed

    @app_commands.command(name="prestige", description="What two crew members prestige into.")
    @app_commands.describe(crew1="First crew", crew2="Second crew")
    async def prestige(self, interaction: discord.Interaction, crew1: str, crew2: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = await self._data()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        c1 = data.find_character(crew1)
        c2 = data.find_character(crew2)
        if c1 is None or c2 is None:
            missing = crew1 if c1 is None else crew2
            await interaction.followup.send(f"Couldn't find crew **{missing}**.")
            return

        api = self.bot.api  # type: ignore[attr-defined]
        try:
            recipes = await api.prestige_from(int(c1["CharacterDesignId"]))
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        target_id = int(c2["CharacterDesignId"])
        result = None
        for r in recipes:
            ids = {int(r.get("CharacterDesignId1", -1)), int(r.get("CharacterDesignId2", -1))}
            if int(c1["CharacterDesignId"]) in ids and target_id in ids:
                result = r
                break

        n1 = c1["CharacterDesignName"]
        n2 = c2["CharacterDesignName"]
        if result is None:
            await interaction.followup.send(
                f"**{n1}** + **{n2}** don't prestige into anything. "
                "(Not every pair has a recipe.)"
            )
            return

        out = data.char_name(result["ToCharacterDesignId"])
        out_char = data.characters.get(int(result["ToCharacterDesignId"]))
        icon = rarity_icon(out_char.get("Rarity", "")) if out_char else "✨"
        embed = discord.Embed(
            title="⚗️ Prestige result",
            description=f"**{n1}** ➕ **{n2}**\n➡️ {icon} **{out}**",
            color=config.BOT_COLOR,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="prestige-recipes", description="All ways to obtain a crew via prestige."
    )
    @app_commands.describe(name="Target crew to build")
    async def prestige_recipes(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = await self._data()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        char = data.find_character(name)
        if char is None:
            await interaction.followup.send(f"No crew found matching **{name}**.")
            return

        api = self.bot.api  # type: ignore[attr-defined]
        try:
            recipes = await api.prestige_to(int(char["CharacterDesignId"]))
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        if not recipes:
            await interaction.followup.send(
                f"**{char['CharacterDesignName']}** cannot be made by prestige "
                "(it may be a collectible or special crew)."
            )
            return

        # Deduplicate unordered pairs.
        seen: set[frozenset[int]] = set()
        lines: list[str] = []
        for r in recipes:
            pair = frozenset(
                {int(r.get("CharacterDesignId1", -1)), int(r.get("CharacterDesignId2", -1))}
            )
            if pair in seen:
                continue
            seen.add(pair)
            a = data.char_name(r.get("CharacterDesignId1"))
            b = data.char_name(r.get("CharacterDesignId2"))
            lines.append(f"• {a} ➕ {b}")

        icon = rarity_icon(char.get("Rarity", ""))
        embed = discord.Embed(
            title=f"⚗️ Recipes for {icon} {char['CharacterDesignName']}",
            description="\n".join(lines[:30]) or "No recipes.",
            color=config.BOT_COLOR,
        )
        if len(lines) > 30:
            embed.set_footer(text=f"Showing 30 of {len(lines)} recipes.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Crew(bot))
