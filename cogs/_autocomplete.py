"""Shared slash-command autocomplete helpers backed by the game-data cache."""
from __future__ import annotations

import discord
from discord import app_commands


async def suggest(interaction: discord.Interaction, current: str, method: str) -> list[app_commands.Choice[str]]:
    """Return up to 25 name suggestions from GameData.<method>(current).

    Fails soft: on any error (cache not ready, etc.) returns no suggestions so
    the user can still type a name freely.
    """
    data = getattr(interaction.client, "data", None)
    if data is None:
        return []
    try:
        await data.ensure_loaded()
        names = getattr(data, method)(current or "")
    except Exception:
        return []
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names[:25]]
