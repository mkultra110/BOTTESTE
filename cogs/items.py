"""Item lookup commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clean_text, num, rarity_icon


class Items(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="item", description="Look up an item's details and market price.")
    @app_commands.describe(name="Item name (or part of it)")
    async def item(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        data = self.bot.data  # type: ignore[attr-defined]
        try:
            await data.ensure_loaded()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ Could not load game data: {exc}")
            return

        it = data.find_item(name)
        if it is None:
            suggestions = data.find_items(name, limit=8)
            if suggestions:
                names = ", ".join(f"**{s['ItemDesignName']}**" for s in suggestions)
                await interaction.followup.send(
                    f"No exact match for “{name}”. Did you mean: {names}?"
                )
            else:
                await interaction.followup.send(f"No item found matching **{name}**.")
            return

        await interaction.followup.send(embed=self._item_embed(it))

    def _item_embed(self, it: dict[str, str]) -> discord.Embed:
        rarity = it.get("Rarity", "Common")
        embed = discord.Embed(
            title=f"{rarity_icon(rarity)} {it.get('ItemDesignName', '?')}",
            description=clean_text(it.get("ItemDesignDescription")),
            color=config.BOT_COLOR,
        )
        embed.add_field(name="Rarity", value=rarity, inline=True)
        if it.get("ItemType") and it["ItemType"] != "None":
            embed.add_field(name="Type", value=it["ItemType"], inline=True)
        if it.get("ItemSubType") and it["ItemSubType"] != "None":
            embed.add_field(name="Subtype", value=it["ItemSubType"], inline=True)

        # Enhancement / bonus
        if it.get("EnhancementType") and it["EnhancementType"] != "None":
            val = it.get("EnhancementValue", "")
            embed.add_field(
                name="✨ Bonus",
                value=f"{it['EnhancementType']} +{val}",
                inline=True,
            )

        # Prices
        market = it.get("MarketPrice")
        fair = it.get("FairPrice")
        price_bits = []
        if market and market != "0":
            price_bits.append(f"Market: **{num(market)}** 💰")
        if fair and fair != "0":
            price_bits.append(f"Fair: **{num(fair)}** 💰")
        if price_bits:
            embed.add_field(name="Prices (Starbux)", value="\n".join(price_bits), inline=False)

        # Crafting ingredients
        ingredients = it.get("Ingredients")
        if ingredients:
            parts = []
            for chunk in ingredients.split("|"):
                if "x" in chunk:
                    iid, _, qty = chunk.partition("x")
                    try:
                        name = self.bot.data.items.get(int(iid), {}).get("ItemDesignName", f"#{iid}")  # type: ignore[attr-defined]
                    except ValueError:
                        name = f"#{iid}"
                    parts.append(f"{qty}× {name}")
            if parts:
                embed.add_field(name="🧪 Crafted from", value=", ".join(parts), inline=False)

        embed.set_footer(text=f"Item ID {it.get('ItemDesignId', '?')}")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Items(bot))
