"""Entry point for the Pixel Starships Discord bot."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from pss import GameData, PSSApi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

INITIAL_COGS = (
    "cogs.general",
    "cogs.players",
    "cogs.fleets",
    "cogs.crew",
    "cogs.items",
    "cogs.daily",
    "cogs.collections",
    "cogs.rooms",
    "cogs.ships",
    "cogs.recruit",
)


class PSSBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()  # slash commands need no privileged intents
        super().__init__(command_prefix="!pss ", intents=intents, help_command=None)
        self.api = PSSApi(
            host=config.PSS_API_HOST,
            language=config.PSS_LANGUAGE,
            checksum_key=config.PSS_DEVICE_CHECKSUM_KEY,
        )
        self.data = GameData(self.api, ttl=config.CACHE_TTL_SECONDS)

    async def setup_hook(self) -> None:
        self.tree.on_error = self.on_app_command_error
        await self.api.start()
        try:
            await self.data.ensure_loaded()
        except Exception as exc:  # non-fatal; cogs retry on demand
            log.warning("Initial game-data load failed (will retry lazily): %s", exc)

        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception:
                log.exception("Failed to load %s", ext)

        if config.DISCORD_GUILD_ID:
            guild = discord.Object(id=config.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), config.DISCORD_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands", len(synced))

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        log.exception("Unhandled app-command error", exc_info=error)
        msg = "⚠️ Something went wrong handling that command. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        activity = discord.Game(name="Pixel Starships | /help")
        await self.change_presence(activity=activity)

    async def close(self) -> None:
        await self.api.close()
        await super().close()


def main() -> None:
    config.require_token()
    bot = PSSBot()
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
