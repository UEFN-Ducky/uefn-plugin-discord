"""Discord UEFN desktop plugin — owns bots/client/poller/presence/commands/tools.

Secrets (bot token, guild, etc.) stay in the app's credentials.dat via set_key —
never ship them in this package.
"""

from __future__ import annotations

import threading
from typing import Any

PLUGIN_ID = "discord"


def register(api: Any) -> None:
    """Register MCP tools, panel RPCs, and start pollers when the host supports them."""
    from .tools import register_tools

    register_tools(api)

    # EXE builds before panel-RPC host work lack api.register_panel_rpc — do not crash.
    if hasattr(api, "register_panel_rpc"):
        from .panel_rpc import register_panel_rpcs

        register_panel_rpcs(api)
        if api.is_enabled():
            # Never block Store enable/disable on Discord gateway connect.
            threading.Thread(
                target=_start_runtime_safe,
                args=(api.log,),
                daemon=True,
                name="discord-runtime-start",
            ).start()
    else:
        api.log(
            "Host lacks register_panel_rpc — Discord tools registered; "
            "panel HTML RPCs/pollers need a newer UEFN-Ducky build"
        )

    api.log("Discord plugin registered")


def unload() -> None:
    """Called by the host before Store update/disable drops this module."""
    _stop_runtime()


def _start_runtime_safe(log_fn: Any) -> None:
    try:
        _start_runtime()
        try:
            log_fn("Discord poller/presence started")
        except Exception:
            pass
    except Exception as exc:
        try:
            log_fn(f"Discord runtime start failed: {exc}")
        except Exception:
            pass


def _start_runtime() -> None:
    from . import poller, presence

    # Drop orphan pollers from a previous register()/module load (sys registry +
    # generation bump) before starting fresh — module-local state alone misses them.
    try:
        poller.stop_all(join_timeout_s=2.5)
    except Exception:
        pass
    presence.set_plugin_active(True)
    presence.ensure_all_enabled()
    poller.sync_enabled_bots()


def _stop_runtime() -> None:
    try:
        from . import poller, presence

        presence.set_plugin_active(False)
        try:
            poller.stop_all(join_timeout_s=2.0)
        except Exception:
            pass
    except Exception:
        pass
