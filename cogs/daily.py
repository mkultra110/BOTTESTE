"""Daily offers / LiveOps command, plus the optional top-players leaderboard."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from pss import PSSApiError
from pss.formatting import clean_text, num, relative_time


class Daily(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="daily", description="Today's offers, sale, daily reward and news.")
    async def daily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        api = self.bot.api  # type: ignore[attr-defined]
        data = self.bot.data  # type: ignore[attr-defined]
        try:
            ops = await api.today_liveops()
            await data.ensure_loaded()
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        embed = discord.Embed(
            title="📅 Pixel Starships — Today",
            color=config.BOT_COLOR,
        )

        news = clean_text(ops.get("News"))
        if news:
            embed.description = f"📰 {news}"

        # Daily reward
        reward_type = ops.get("DailyRewardType")
        reward_arg = ops.get("DailyRewardArgument")
        if reward_type:
            reward = f"{num(reward_arg)} {reward_type}" if reward_arg else reward_type
            rewards = ops.get("DailyItemRewards")
            if rewards:
                reward += f" + items ({self._item_list(data, rewards)})"
            embed.add_field(name="🎁 Daily reward", value=reward, inline=False)

        # Daily sale
        sale_arg = ops.get("SaleArgument")
        sale_type = ops.get("SaleType")
        if sale_type and sale_type != "None" and sale_arg:
            label = self._resolve(data, sale_type, sale_arg)
            price = self._sale_price(ops.get("SaleRewardString"))
            price_str = f" — {price}" if price else ""
            value = f"{self._friendly_type(sale_type)}: {label}{price_str}"
            end = ops.get("SaleEndDate")
            if end:
                value += f"\nEnds {relative_time(end)}"
            embed.add_field(name="🏷️ Daily sale", value=value, inline=False)

        # Limited shop offer
        cat_type = ops.get("LimitedCatalogType")
        cat_arg = ops.get("LimitedCatalogArgument")
        if cat_type and cat_type != "None" and cat_arg:
            label = self._resolve(data, cat_type, cat_arg)
            price = ops.get("LimitedCatalogCurrencyAmount")
            currency = ops.get("LimitedCatalogCurrencyType", "")
            price_str = f" — {num(price)} {currency}" if price else ""
            # LimitedCatalogQuantity is the *remaining stock* (it depletes over
            # the day from LimitedCatalogRestockQuantity), not a bundle size.
            left = ops.get("LimitedCatalogQuantity")
            restock = ops.get("LimitedCatalogRestockQuantity")
            stock_str = ""
            if left:
                # Only note the restock amount once some stock has actually sold.
                if restock and restock not in ("0", left):
                    stock_str = f" ({left} of {restock} left)"
                else:
                    stock_str = f" ({left} in stock)"
            embed.add_field(name="🛒 Shop offer", value=f"{label}{price_str}{stock_str}", inline=False)
            expiry = ops.get("LimitedCatalogExpiryDate")
            if expiry:
                embed.add_field(name="⏳ Shop resets", value=relative_time(expiry), inline=True)

        # Dropship cargo merchant
        cargo = self._cargo(data, ops.get("CargoItems"), ops.get("CargoPrices"))
        if cargo:
            embed.add_field(name="🚚 Cargo merchant", value=cargo, inline=False)

        # Featured crew
        common = ops.get("CommonCrewId")
        hero = ops.get("HeroCrewId")
        crew_bits = []
        if common and common != "0":
            crew_bits.append(f"Daily: **{data.char_name(common)}**")
        if hero and hero != "0":
            crew_bits.append(f"Hero: **{data.char_name(hero)}**")
        if crew_bits:
            embed.add_field(name="🧑‍🚀 Featured crew", value=" • ".join(crew_bits), inline=False)

        embed.set_footer(text="Resets daily at 00:00 UTC")
        await interaction.followup.send(embed=embed)

    FRIENDLY_TYPES = {
        "FleetGift": "Fleet gift",
        "LimitedCatalog": "Limited offer",
        "Bonus": "Bonus",
    }

    def _friendly_type(self, kind: str) -> str:
        return self.FRIENDLY_TYPES.get(kind, kind)

    def _resolve(self, data, kind: str, arg: str) -> str:
        """Resolve an item/character id (or bonus) to a readable label."""
        if kind == "Bonus":
            return f"+{arg}% bonus"
        try:
            arg_id = int(arg)
        except (TypeError, ValueError):
            return str(arg)
        if kind in ("Item", "FleetGift"):
            it = data.items.get(arg_id)
            if it:
                return it.get("ItemDesignName", f"#{arg_id}")
        if kind in ("Character", "Crew"):
            return data.char_name(arg_id)
        return f"#{arg_id}"

    def _sale_price(self, reward_string: str | None) -> str:
        """Extract a real-money price from a SaleRewardString like
        'item:1187x[USD/2]' -> 'USD 2'."""
        if not reward_string or "[" not in reward_string:
            return ""
        try:
            inside = reward_string.split("[", 1)[1].split("]", 1)[0]
            currency, _, amount = inside.partition("/")
            return f"{currency} {amount}".strip()
        except (IndexError, ValueError):
            return ""

    def _cargo(self, data, items_raw: str | None, prices_raw: str | None) -> str:
        """Pair CargoItems ('836x1|...') with CargoPrices ('starbux:100|...')."""
        if not items_raw:
            return ""
        items = items_raw.split("|")
        prices = (prices_raw or "").split("|")
        lines = []
        for i, chunk in enumerate(items):
            if "x" not in chunk:
                continue
            iid, _, qty = chunk.partition("x")
            try:
                name = data.items.get(int(iid), {}).get("ItemDesignName", f"#{iid}")
            except ValueError:
                name = f"#{iid}"
            price = ""
            if i < len(prices) and ":" in prices[i]:
                cur, _, amt = prices[i].partition(":")
                price = f" — {num(amt)} {cur}"
            lines.append(f"{qty}× {name}{price}")
        return "\n".join(lines)

    def _item_list(self, data, raw: str) -> str:
        parts = []
        for chunk in raw.split("|"):
            if "x" in chunk:
                iid, _, qty = chunk.partition("x")
                try:
                    name = data.items.get(int(iid), {}).get("ItemDesignName", f"#{iid}")
                except ValueError:
                    name = f"#{iid}"
                parts.append(f"{qty}× {name}")
        return ", ".join(parts)

    # -- optional authenticated leaderboard --------------------------------
    @app_commands.command(name="top-players", description="Global player leaderboard (needs auth).")
    @app_commands.describe(count="How many players to show (1-25, default 10)")
    async def top_players(self, interaction: discord.Interaction, count: int = 10) -> None:
        api = self.bot.api  # type: ignore[attr-defined]
        if not getattr(api, "has_auth", False):
            await interaction.response.send_message(
                "🔒 This command needs an authenticated PSS device token "
                "(set `PSS_DEVICE_CHECKSUM_KEY`). It's disabled on this bot.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        count = max(1, min(count, 25))
        try:
            players = await api.top_players(take=count)
        except PSSApiError as exc:
            await interaction.followup.send(f"⚠️ API error: {exc}")
            return

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        lines = []
        for i, p in enumerate(players[:count]):
            rank = medals.get(i, f"`#{i + 1}`")
            lines.append(
                f"{rank} **{p.get('Name', '?')}** — 🏆 {num(p.get('Trophy'))}"
                + (f" • {p.get('AllianceName')}" if p.get("AllianceName") else "")
            )
        embed = discord.Embed(
            title="🏆 Top players",
            description="\n".join(lines) or "No data.",
            color=config.BOT_COLOR,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Daily(bot))
