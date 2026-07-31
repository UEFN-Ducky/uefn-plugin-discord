"""Presence: Online by default; show_offline → invisible; intent fallback flag."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from . import presence


def test_desired_presence_online_by_default() -> None:
    with patch.object(presence._bots, "get_bot", return_value=None):
        assert presence.desired_presence_status("default") == "online"
        assert presence._presence_payload("default")["status"] == "online"


def test_desired_presence_invisible_when_show_offline() -> None:
    bot = SimpleNamespace(show_offline=True, enabled=True)
    with patch.object(presence._bots, "get_bot", return_value=bot):
        assert presence.desired_presence_status("default") == "invisible"


def test_intent_ladder_and_basic_flag() -> None:
    """FULL → MEMBERS → BASIC after 4014; BASIC mirrors _basic_intents_bots."""
    bid = "test-offline-bot"
    with presence._lock:
        presence._basic_intents_bots.discard(bid)
        presence._intent_level.pop(bid, None)
    assert presence._INTENTS_DM == 1 << 12
    assert presence._INTENTS_BASIC == (1 << 0) | presence._INTENTS_DM
    assert presence._INTENTS_MEMBERS == (1 << 0) | (1 << 1) | presence._INTENTS_DM
    assert presence._INTENTS_FULL & (1 << 8)  # GUILD_PRESENCES bit
    assert presence._INTENTS_FULL & presence._INTENTS_DM
    with presence._lock:
        presence._intent_level[bid] = presence._LEVEL_MEMBERS
    assert presence.intent_level(bid) == presence._LEVEL_MEMBERS
    with presence._lock:
        presence._intent_level[bid] = presence._LEVEL_BASIC
        presence._basic_intents_bots.add(bid)
        assert bid in presence._basic_intents_bots
    assert presence.intent_level(bid) == presence._LEVEL_BASIC
    with presence._lock:
        presence._basic_intents_bots.discard(bid)
        presence._intent_level.pop(bid, None)


def test_bump_presence_marks_dirty() -> None:
    bid = "bump-test"
    with presence._lock:
        presence._presence_bump.discard(bid)
        presence._started_bots.add(bid)  # skip spawning a real gateway thread
    presence.bump_presence(bid)
    with presence._lock:
        assert bid in presence._presence_bump
        presence._presence_bump.discard(bid)
        presence._started_bots.discard(bid)


if __name__ == "__main__":
    test_desired_presence_online_by_default()
    test_desired_presence_invisible_when_show_offline()
    test_intent_ladder_and_basic_flag()
    test_bump_presence_marks_dirty()
    print("ok presence online")
