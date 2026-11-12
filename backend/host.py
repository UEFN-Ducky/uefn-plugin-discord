"""App functions this plugin calls, found where the running app keeps them.

Newer apps split ``frontend.ui_web.project_chats`` into ``chats/*`` and ``agent_modes`` into
``agent_turns/*`` and deleted the old modules; older apps only have the old ones.
"""

from __future__ import annotations

import importlib
from typing import Any

_PLACES = (
    "frontend.ui_web.chats.conversations",
    "frontend.ui_web.agent_turns.push",
    "frontend.ui_web.agent_turns.routing",
    "frontend.ui_web.agent_turns.run",
    "frontend.ui_web.agent_turns.state",
    "frontend.ui_web.project_chats",
    "frontend.ui_web.agent_modes",
)


def host(name: str) -> Any:
    """The app's ``name`` (e.g. ``create_conversation``); ImportError when no module has it."""
    for place in _PLACES:
        try:
            mod = importlib.import_module(place)
        except ImportError:
            continue
        if hasattr(mod, name):
            return getattr(mod, name)
    raise ImportError(f"this Ducky app has no {name}")
