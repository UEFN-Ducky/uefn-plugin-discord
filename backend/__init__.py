"""Discord UEFN desktop plugin — registers agent tools when enabled.

Secrets (bot token, guild, etc.) stay in the app's credentials.dat via set_key —
never ship them in this package.
"""

from __future__ import annotations


def register(api) -> None:
    """Import Discord MCP tools onto the shared FastMCP instance (idempotent)."""
    # Phase 1: tools still live in the app; this plugin only gates registration.
    import backend.tools.discord_tools  # noqa: F401

    api.log("Discord tools registered")
