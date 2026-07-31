"""Discord chat commands — drive your duckies from inside your server.

Each bot answers only its own prefix (default ``!ducky``), so multiple bots in
the same channel never double-reply.

    !ducky                      → roster of duckies (agent profiles)
    !ducky list                 → same
    !ducky <name> <message>     → run that ducky and post its reply back

The poller feeds every new human message through ``maybe_handle``. A command
runs on its own daemon thread (agent turns take 10s-minutes), keeps ONE
persistent chat per (bot, channel, ducky) so follow-ups retain context, and
posts the reply as that bot. Bot-authored messages are ignored — no reply loops.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from backend.agent.a2a_format import wrap_untrusted

from . import bots, client

DEFAULT_PREFIX = bots.DEFAULT_PREFIX
_MAX_DISCORD = 1900  # Discord cap is 2000; leave room for the name prefix.
_TIMEOUT_S = 300.0
_SEEN_CAP = 512
_CLAIM_TTL_S = 3600.0
# Survives module reload so orphan poller threads + new code share one dedupe set.
_SEEN_ATTR = "_uefn_discord_cmd_seen"

_lock = threading.Lock()
# One persistent chat per (bot_id, channel_id, profile_id) — follow-ups keep context.
_convs: dict[tuple[str, str, str], str] = {}
_busy: set[tuple[str, str, str]] = set()
_lock_hint_sent: set[str] = set()


def allowed_ids(bot_id: str | None = None) -> set[str]:
    """Discord user IDs permitted to run commands. Empty = locked; {"*"} = anyone."""
    raw = bots.get_allowed_ids(bot_id)
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_authorized(author_id: str, allowed: set[str]) -> bool:
    """A command runs only from an allow-listed author (or "*" = anyone)."""
    return "*" in allowed or (bool(author_id) and author_id in allowed)


def _claims_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "UEFN-Ducky" / "discord_cmd_claims"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_command_leader() -> bool:
    """Only one UEFN-Ducky process should run !commands (many EXEs can be open)."""
    path = _claims_dir().parent / "discord_commander.lock"
    my_pid = os.getpid()
    now = time.time()
    try:
        if path.is_file():
            raw = path.read_text(encoding="utf-8").strip().split()
            other = int(raw[0]) if raw else 0
            ts = float(raw[1]) if len(raw) > 1 else 0.0
            if other != my_pid and _pid_alive(other) and (now - ts) < 45.0:
                return False
        path.write_text(f"{my_pid} {now:.3f}", encoding="utf-8")
        return True
    except Exception:
        # If lock I/O fails, still allow — per-message file claim is the hard gate.
        return True


def _prune_claims(folder: Path) -> None:
    cutoff = time.time() - _CLAIM_TTL_S
    try:
        for p in folder.iterdir():
            if not p.is_file():
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def _seen_store() -> dict[str, Any]:
    store = getattr(sys, _SEEN_ATTR, None)
    if not isinstance(store, dict) or "lock" not in store:
        store = {"lock": threading.Lock(), "order": [], "set": set()}
        setattr(sys, _SEEN_ATTR, store)
    return store


def _claim_message(message_id: str, *, channel_id: str = "", content: str = "") -> bool:
    """True once per Discord message across threads AND processes.

    In-process set on ``sys`` plus atomic claim files under AppData so a second
    UEFN-Ducky.exe cannot also reply to the same ``!bob``.
    """
    mid = (message_id or "").strip()
    if mid:
        mem_key = f"id:{mid}"
        file_key = mid
    else:
        body = (content or "").strip().lower()
        if not body:
            return True
        mem_key = f"fp:{(channel_id or '').strip()}\0{body}"
        # Keep filename safe / short.
        file_key = f"fp_{abs(hash(mem_key)) & 0xFFFFFFFF:08x}"
    store = _seen_store()
    with store["lock"]:
        seen: set[str] = store["set"]
        order: list[str] = store["order"]
        if mem_key in seen:
            return False
        seen.add(mem_key)
        order.append(mem_key)
        while len(order) > _SEEN_CAP:
            old = order.pop(0)
            seen.discard(old)
    # Cross-process gate (survives multiple UEFN-Ducky.exe).
    folder = _claims_dir()
    _prune_claims(folder)
    claim = folder / f"{file_key}.claimed"
    try:
        fd = os.open(str(claim), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()} {time.time():.3f}".encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        # Disk weirdness — keep in-process claim only.
        return True


def maybe_handle(message: dict[str, Any], channel_id: str, *, bot_id: str | None = None) -> bool:
    """True when the message is this bot's command (handled on a background thread)."""
    if message.get("bot"):
        return False
    # Another live UEFN-Ducky process already owns !commands — stay silent.
    if not is_command_leader():
        return False
    bid = (bot_id or bots.DEFAULT_BOT_ID).strip() or bots.DEFAULT_BOT_ID
    prefix = bots.get_prefix(bid)
    text = str(message.get("content") or "").strip()
    text_l = text.lower()
    prefix_l = prefix.lower()
    # Exact prefix or prefix + space — "!ducky" / "!ducky x" yes; "!duckyx" no.
    if not (text_l == prefix_l or text_l.startswith(prefix_l + " ")):
        return False
    # Claim before any side effect so orphan pollers / other EXEs cannot multi-reply.
    if not _claim_message(
        str(message.get("id") or ""),
        channel_id=channel_id,
        content=text,
    ):
        return False
    rest_raw = text[len(prefix) :]
    whoami_rest = rest_raw.strip().lower()
    if whoami_rest == "whoami":
        author_id = str(message.get("author_id") or "?")
        threading.Thread(
            target=_send,
            args=(
                channel_id,
                f"🦆 Your Discord user ID is `{author_id}` — paste it into "
                "Settings → Discord → “!ducky access” (or this bot’s access field) "
                "to let this account run commands.",
                bid,
            ),
            daemon=True,
            name=f"discord-whoami-{bid}",
        ).start()
        return True
    allowed = allowed_ids(bid)
    if not is_authorized(str(message.get("author_id") or ""), allowed):
        if not allowed and bid not in _lock_hint_sent:
            _lock_hint_sent.add(bid)
            threading.Thread(
                target=_send,
                args=(
                    channel_id,
                    f"🦆 `{prefix}` is locked. The app owner enables it in "
                    "Settings → Discord by adding allowed Discord user IDs.",
                    bid,
                ),
                daemon=True,
                name=f"discord-lock-hint-{bid}",
            ).start()
        return False
    threading.Thread(
        target=_run_command,
        args=(text, channel_id, str(message.get("author") or "someone"), bid, prefix),
        daemon=True,
        name=f"discord-cmd-{bid}",
    ).start()
    return True


def match_profile(profiles: list[dict[str, Any]], rest: str) -> tuple[dict[str, Any] | None, str]:
    """Resolve a ducky from the text after the prefix; return (profile, remaining message).

    Prefer exact profile id ("verse-coder fix x"), then longest unique full-name
    match ("verse coder fix x" → Verse Coder), else the first word as a unique
    name prefix ("verse fix x" → Verse Coder). Ambiguous duplicate names refuse
    to guess — the roster shows ids.
    """
    rest_l = rest.lower().strip()
    if not rest_l:
        return None, ""
    # Stable id first — survives renames and duplicate display names.
    for p in profiles:
        pid = str(p.get("id") or "").strip().lower()
        if pid and (rest_l == pid or rest_l.startswith(pid + " ")):
            return p, rest[len(pid) :].strip()
    name_hits: list[tuple[dict[str, Any], int]] = []
    for p in profiles:
        name_l = str(p.get("name") or "").strip().lower()
        if name_l and (rest_l == name_l or rest_l.startswith(name_l + " ")):
            name_hits.append((p, len(name_l)))
    if name_hits:
        best_len = max(n for _, n in name_hits)
        tied = [p for p, n in name_hits if n == best_len]
        if len(tied) == 1:
            return tied[0], rest[best_len:].strip()
        return None, rest
    first = rest_l.split()[0]
    prefix_hits = [
        p for p in profiles if str(p.get("name") or "").strip().lower().startswith(first)
    ]
    if len(prefix_hits) == 1:
        parts = rest.split(None, 1)
        return prefix_hits[0], parts[1].strip() if len(parts) > 1 else ""
    return None, rest


def _send(channel_id: str, text: str, bot_id: str = bots.DEFAULT_BOT_ID) -> None:
    try:
        client.send_message(channel_id, text[: _MAX_DISCORD + 100], bot_id=bot_id)
    except client.DiscordError:
        pass


def _roster_text(prefix: str) -> str:
    from frontend.agent_profiles import list_agent_profiles_available

    lines = [
        f"🦆 **Your duckies** — `{prefix} <id|name> <message>` "
        "(use **id** when two share a name):"
    ]
    for p in list_agent_profiles_available():
        name = str(p.get("name") or "").strip()
        pid = str(p.get("id") or "").strip()
        if not name and not pid:
            continue
        use = str(p.get("when_to_use") or "").strip()
        label = f"**{name}** (`{pid}`)" if pid else f"**{name}**"
        lines.append(f"• {label}" + (f" — {use[:90]}" if use else ""))
    return "\n".join(lines)[:_MAX_DISCORD]


def _spawn_conv(profile: dict[str, Any]) -> str:
    from backend.tools.panel.ducky_panel import _profile_spawn_kwargs
    from frontend.settings import PanelSettings
    from frontend.ui_web.agent_modes import notify_chats_changed
    from frontend.ui_web.project_chats import create_conversation

    persona = _profile_spawn_kwargs(profile)
    name = str(profile.get("name") or "Ducky").strip()
    conv = create_conversation(
        folder_id="",
        title=f"Discord · {name}",
        project_root=PanelSettings.load().uefn_project_root.strip(),
        **persona,
    )
    notify_chats_changed(conv.id, conv.title, conv.folder_id)
    return conv.id


def _run_command(text: str, channel_id: str, author: str, bot_id: str, prefix: str) -> None:
    try:
        rest = text[len(prefix) :].strip()
        if not rest or rest.lower() in ("list", "help", "duckies"):
            _send(channel_id, _roster_text(prefix), bot_id)
            return

        from frontend.agent_profiles import list_agent_profiles_available
        from frontend.ui_web.agent_modes import run_message_and_wait

        profile, message = match_profile(list_agent_profiles_available(), rest)
        if profile is None:
            _send(
                channel_id,
                f"🦆 No ducky matches `{rest.split()[0]}` — try `{prefix} list`.",
                bot_id,
            )
            return
        name = str(profile.get("name") or "Ducky").strip()
        if not message:
            _send(
                channel_id,
                f"🦆 What should **{name}** do? `{prefix} {name.lower()} <message>`",
                bot_id,
            )
            return

        key = (bot_id, channel_id, str(profile.get("id") or name))
        with _lock:
            if key in _busy:
                _send(channel_id, f"🦆 **{name}** is still working — one job at a time.", bot_id)
                return
            _busy.add(key)
        try:
            conv_id = _convs.get(key)
            if not conv_id:
                conv_id = _spawn_conv(profile)
                _convs[key] = conv_id
            _send(channel_id, f"🦆 **{name}** is on it…", bot_id)
            outcome = run_message_and_wait(
                conv_id,
                f"(via Discord, from {author}) {wrap_untrusted(message, 'discord')}",
                "agent",
                timeout_sec=_TIMEOUT_S,
                cancel_on_timeout=False,
            )
            status = str(outcome.get("status") or "")
            if status == "done":
                reply = str(outcome.get("assistant_text") or "").strip() or "(no reply text)"
                _send(channel_id, f"🦆 **{name}:** {reply[:_MAX_DISCORD]}", bot_id)
            elif status == "timeout":
                _send(
                    channel_id,
                    f"🦆 **{name}** is taking longer than {int(_TIMEOUT_S)}s — "
                    f"still working; see the app chat “Discord · {name}”.",
                    bot_id,
                )
            else:
                # ponytail: stale/deleted chat → drop the mapping so the next command respawns
                _convs.pop(key, None)
                _send(
                    channel_id,
                    f"🦆 **{name}** hit an error: {outcome.get('error') or status}",
                    bot_id,
                )
        finally:
            with _lock:
                _busy.discard(key)
    except Exception as e:  # never let a command thread die silently
        _send(channel_id, f"🦆 Command failed: {e}", bot_id)


# Back-compat alias used by older self-checks / imports.
PREFIX = DEFAULT_PREFIX


if __name__ == "__main__":  # pragma: no cover - offline self-check
    roster = [{"id": "1", "name": "Verse Coder"}, {"id": "2", "name": "Level Designer"}]
    p, m = match_profile(roster, "verse coder fix my trigger")
    assert p and p["id"] == "1" and m == "fix my trigger", (p, m)
    p, m = match_profile(roster, "verse fix my trigger")
    assert p and p["id"] == "1" and m == "fix my trigger", (p, m)
    p, m = match_profile(roster, "level")
    assert p and p["id"] == "2" and m == "", (p, m)
    p, m = match_profile(roster, "nosuch thing")
    assert p is None, p
    assert not maybe_handle({"bot": True, "content": "!ducky list"}, "c")
    assert not maybe_handle({"content": "hello"}, "c")
    # Authorization gate: only allow-listed ids (or "*") may run commands.
    assert is_authorized("42", {"42"}) and is_authorized("42", {"*"})
    assert not is_authorized("42", {"7"}) and not is_authorized("42", set())
    assert not is_authorized("", set())  # blank author, locked → denied
    print("commands self-check ok")
