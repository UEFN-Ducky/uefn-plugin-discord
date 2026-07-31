"""Watched-channel state for the Discord panel (no REST command poller).

Real Discord bots receive messages on the Gateway (``MESSAGE_CREATE`` in
``presence.py``). This module only remembers which channel the panel has open
for diagnose / last-used persistence. History is loaded via one-shot REST in
``panel_rpc.open_channel`` / ``fetch_messages``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from . import bots, client

_lock = threading.Lock()
_states: dict[str, "_Watch"] = {}


@dataclass
class _Watch:
    bot_id: str
    active_channel: str | None = None
    last_id: str | None = None
    last_seen: dict[str, Any] | None = None
    opened_ts: float = 0.0


def _get_or_create(bot_id: str) -> _Watch:
    bid = (bot_id or bots.DEFAULT_BOT_ID).strip() or bots.DEFAULT_BOT_ID
    with _lock:
        st = _states.get(bid)
        if st is None:
            st = _Watch(bot_id=bid)
            _states[bid] = st
        return st


def watched_channel(bot_id: str | None = None) -> str:
    st = _get_or_create(bot_id)
    with _lock:
        return str(st.active_channel or "")


def note_message(message: dict[str, Any], channel_id: str, bot_id: str) -> None:
    """Update diagnose snapshot when the gateway sees a message in the open channel."""
    st = _get_or_create(bot_id)
    with _lock:
        if st.active_channel != channel_id:
            return
        mid = str(message.get("id") or "")
        if mid:
            st.last_id = mid
        st.last_seen = {
            "channel_id": channel_id,
            "author": message.get("author", ""),
            "content_len": len(str(message.get("content") or "")),
            "preview": (str(message.get("content") or ""))[:60],
            "ts": message.get("timestamp", ""),
        }


def debug_state(bot_id: str | None = None) -> dict[str, Any]:
    bid = (bot_id or bots.DEFAULT_BOT_ID).strip() or bots.DEFAULT_BOT_ID
    st = _get_or_create(bid)
    leader = False
    try:
        from . import commands

        leader = commands.is_command_leader()
    except Exception:
        leader = False
    with _lock:
        return {
            "bot_id": bid,
            "watching_channel_id": st.active_channel or "",
            "poller_alive": False,
            "mode": "gateway",
            "command_leader": leader,
            "pid": __import__("os").getpid(),
            "last_poll_age_s": None,
            "last_seen": st.last_seen,
            "opened_age_s": round(time.time() - st.opened_ts, 1) if st.opened_ts else None,
        }


def open_channel(channel_id: str, newest_id: str | None, *, bot_id: str | None = None) -> None:
    """Remember the panel's open channel (no background REST loop)."""
    st = _get_or_create(bot_id)
    with _lock:
        st.active_channel = (channel_id or "").strip() or None
        st.last_id = newest_id
        st.opened_ts = time.time()


def stop(bot_id: str | None = None) -> None:
    st = _get_or_create(bot_id)
    with _lock:
        st.active_channel = None


def stop_bot(bot_id: str, *, join_timeout_s: float = 2.0) -> None:
    del join_timeout_s  # no threads
    bid = (bot_id or "").strip()
    with _lock:
        _states.pop(bid, None)


def stop_all(*, join_timeout_s: float = 2.0) -> None:
    del join_timeout_s
    with _lock:
        _states.clear()


def ensure_watching(channel_id: str, *, bot_id: str | None = None) -> None:
    """Set last-used channel without starting any poller thread."""
    cid = (channel_id or "").strip()
    if not cid:
        return
    st = _get_or_create(bot_id)
    with _lock:
        if st.active_channel:
            return
        st.active_channel = cid
        st.opened_ts = time.time()
    # Optional: seed last_id so UI after-cursors are sane (one REST call, not a loop).
    bid = st.bot_id

    def _boot() -> None:
        try:
            newest = client.fetch_messages(cid, limit=1, bot_id=bid)
        except client.DiscordError:
            return
        with _lock:
            if st.active_channel != cid:
                return
            st.last_id = newest[-1]["id"] if newest else None

    threading.Thread(target=_boot, daemon=True, name=f"discord-watch-boot-{bid}").start()


def sync_enabled_bots() -> None:
    """Attach last-used channels; stop state for disabled bots."""
    enabled_ids = {b.id for b in bots.enabled_bots()}
    with _lock:
        known = set(_states.keys())
    for bid in known - enabled_ids:
        stop_bot(bid)
    for b in bots.enabled_bots():
        if not client.get_token(b.id):
            continue
        cid = bots.get_channel_id(b.id)
        if cid:
            ensure_watching(cid, bot_id=b.id)


if __name__ == "__main__":  # pragma: no cover
    open_channel("c1", "1", bot_id="default")
    assert watched_channel("default") == "c1"
    stop_all()
    print("watch-state self-check ok")
