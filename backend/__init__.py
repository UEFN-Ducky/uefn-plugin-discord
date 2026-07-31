"""Discord UEFN desktop plugin — owns bots/client/poller/presence/commands/tools.

Secrets (bot token, guild, etc.) stay in the app's credentials.dat via set_key —
never ship them in this package.
"""

from __future__ import annotations

from typing import Any

PLUGIN_ID = "discord"


def register(api: Any) -> None:
    """Register MCP tools, panel RPCs, and start pollers when enabled."""
    from .panel_rpc import register_panel_rpcs
    from .tools import register_tools

    register_tools(api)
    register_panel_rpcs(api)

    if api.is_enabled():
        _start_runtime()
        api.log("Discord poller/presence started")

    api.log("Discord plugin registered")


def unload() -> None:
    """Called by the host before Store update/disable drops this module."""
    _stop_runtime()


def _start_runtime() -> None:
    from . import poller, presence

    presence.set_plugin_active(True)
    presence.ensure_all_enabled()
    poller.sync_enabled_bots()


def _stop_runtime() -> None:
    from . import bots, poller, presence

    presence.set_plugin_active(False)
    for profile in bots.list_bots():
        try:
            poller.stop_bot(profile.id)
        except Exception:
            pass
