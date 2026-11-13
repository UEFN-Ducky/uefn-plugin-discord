"""Members column: a blocked member list asks for the Dev Portal switches with a setup card."""

from __future__ import annotations

from . import panel_rpc


def test_intents_fix_only_when_discord_blocks_members():
    assert panel_rpc.intents_fix('Discord 403: {"message": "Missing Access"}', 2) == "intents"
    assert panel_rpc.intents_fix("", 0) == "intents"  # gateway fell back to guilds-only
    assert panel_rpc.intents_fix("Discord request failed: timeout", 2) == ""
