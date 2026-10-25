"""Automations tiles: Gateway emit + discord.send handler."""

from __future__ import annotations

import re
import time
from typing import Any

_api: Any = None

# A GitHub pull request link: owner/repo + number. Only github.com, https only.
_PR_LINK = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/(\d+)\b")
_CHUNK = 1900  # Discord's cap is 2000 per message
_ROLES_TTL_S = 60.0
_roles_cache: tuple[float, list[dict[str, str]]] = (0.0, [])


def register_nodes(api: Any) -> None:
    """Register discord.send. Skip quietly on hosts without the automations plane."""
    global _api
    _api = api
    if not hasattr(api, "register_automation_node"):
        return
    api.register_automation_node("discord.send", handle_send)
    api.register_automation_node("discord.react", handle_react)
    # Not a step: fills the "Bot" dropdowns (options_from) with this PC's bots.
    api.register_automation_node("discord.bots", bot_options)
    api.register_automation_node("discord.roles", role_options)


def clear_api() -> None:
    global _api
    _api = None


def bot_options(_ctx: Any = None) -> list[dict[str, str]]:
    from . import bots

    return [{"id": b.id, "label": b.label} for b in bots.list_bots()]


def role_options(_ctx: Any = None) -> list[dict[str, str]]:
    """The servers' roles for a workflow's Roles setting (cached: the list is built often)."""
    global _roles_cache
    at, rows = _roles_cache
    if rows and time.monotonic() - at < _ROLES_TTL_S:
        return rows
    from . import bots, client

    enabled = bots.enabled_bots()
    out: list[dict[str, str]] = []
    for b in enabled:
        try:
            roles = client.list_roles(bot_id=b.id)
        except Exception:
            continue
        for r in roles:
            # Skip @everyone (its id is the server's) and bot-managed roles.
            if r.get("managed") or r.get("id") == b.guild_id:
                continue
            name = f"@{r.get('name')}"
            out.append({"id": str(r.get("id")), "label": f"{b.label} · {name}" if len(enabled) > 1 else name})
    _roles_cache = (time.monotonic(), out)
    return out


def _bot_user_id(bot_id: str) -> str:
    try:
        from .presence import bot_user_id

        return bot_user_id(bot_id)
    except Exception:
        return ""


def _is_allowed(author_id: str, bot_id: str) -> bool:
    """Same gate as !ducky commands: Settings → Discord allowed user IDs."""
    try:
        from .commands import allowed_ids, is_authorized

        return is_authorized(author_id, allowed_ids(bot_id))
    except Exception:
        return False


def message_payload(msg: dict[str, Any], channel_id: str, bot_id: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    content = str((msg or {}).get("content") or "")
    data = raw if isinstance(raw, dict) else {}
    author_id = str(msg.get("author_id") or "")
    me = _bot_user_id(bot_id)
    mentions = data.get("mentions") if isinstance(data.get("mentions"), list) else []
    mentioned = bool(me) and (
        any(isinstance(u, dict) and str(u.get("id") or "") == me for u in mentions)
        or f"<@{me}>" in content
        or f"<@!{me}>" in content
    )
    prompt = re.sub(rf"<@!?{re.escape(me)}>", "", content).strip() if mentioned else content
    pr = _PR_LINK.search(content)
    member = data.get("member") if isinstance(data.get("member"), dict) else {}
    return {
        "channel_id": str(channel_id or "").strip(),
        "message_id": str(msg.get("id") or data.get("id") or ""),
        "guild_id": str(data.get("guild_id") or ""),
        "bot_id": str(bot_id or ""),
        "author": str(msg.get("author") or ""),
        "author_id": author_id,
        "content": content,
        "prompt": prompt,
        # "yes"/"no" so a trigger's settings match them as typed (Only when @mentioned: yes).
        "mentioned": "yes" if mentioned else "no",
        "allowed": "yes" if _is_allowed(author_id, bot_id) else "no",
        # The author's server roles (none in DMs): a workflow's Roles setting matches any one.
        "role_ids": [str(r) for r in member.get("roles") or []],
        "pr_url": pr.group(0) if pr else "",
        "pr_repo": pr.group(1) if pr else "",
        "pr_owner": pr.group(1).split("/")[0] if pr else "",
        "pr_number": pr.group(2) if pr else "",
    }


def emit_message(msg: dict[str, Any], channel_id: str, bot_id: str, raw: dict[str, Any] | None = None) -> None:
    api = _api
    if api is None or not hasattr(api, "emit_automation"):
        return
    # Every Ducky process with this plugin hears the Gateway: one message started a PR
    # review five times. Claim it once per bot across threads and processes (own key, so
    # the same message can still be a !command).
    from .commands import _claim_message

    mid = str(msg.get("id") or (raw or {}).get("id") or "")
    if not _claim_message(f"wf-{bot_id}-{mid}" if mid else "", channel_id=channel_id, content=f"wf {msg.get('content') or ''}"):
        return
    api.emit_automation("discord.message", message_payload(msg, channel_id, bot_id, raw))


def split_text(text: str, size: int = _CHUNK) -> list[str]:
    """Discord-sized pieces, cut at a line break when one is near the end."""
    out: list[str] = []
    rest = text.strip()
    while len(rest) > size:
        cut = rest.rfind("\n", size // 2, size)
        cut = cut if cut > 0 else size
        out.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n")
    if rest:
        out.append(rest)
    return out


def handle_react(ctx: dict[str, Any]) -> dict[str, Any]:
    """React to the message that started the run: add Emoji, take Remove off (👀 → ✅)."""
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    payload = ctx.get("payload") if isinstance(ctx.get("payload"), dict) else {}
    channel_id = str(cfg.get("channel_id") or payload.get("channel_id") or "").strip()
    message_id = str(cfg.get("message_id") or payload.get("message_id") or "").strip()
    add, drop = str(cfg.get("emoji") or "").strip(), str(cfg.get("remove") or "").strip()
    bot_id = str(cfg.get("bot_id") or payload.get("bot_id") or "").strip() or None
    if not channel_id or not message_id:
        return {"ok": False, "error": "no message to react to (run it from a Discord message trigger)"}
    if not add and not drop:
        return {"ok": False, "error": "emoji required"}
    from . import client

    if drop:
        try:
            client.react(channel_id, message_id, drop, remove=True, bot_id=bot_id)
        except client.DiscordError:
            pass  # it was never there: nothing to take off
    if add:
        client.react(channel_id, message_id, add, bot_id=bot_id)
    return {"ok": True, "channel_id": channel_id, "message_id": message_id, "added": add, "removed": drop}


def handle_send(ctx: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    payload = ctx.get("payload") if isinstance(ctx.get("payload"), dict) else {}
    inputs = ctx.get("inputs") if isinstance(ctx.get("inputs"), dict) else {}
    channel_id = str(cfg.get("channel_id") or payload.get("channel_id") or "").strip()
    wired = str(inputs.get("text") or "").strip()  # an earlier step's reply (Agent → Reply)
    text = wired or str(cfg.get("text") or payload.get("content") or payload.get("text") or "").strip()
    bot_id = str(cfg.get("bot_id") or payload.get("bot_id") or "").strip() or None
    if not channel_id:
        return {"ok": False, "error": "channel_id required"}
    if not text:
        return {"ok": False, "error": "text required"}
    from . import client

    # Answer the message that started the run, in its own channel, as a reply.
    reply_to = str(payload.get("message_id") or "") if channel_id == str(payload.get("channel_id") or "") else ""
    sent: list[dict[str, Any]] = []
    for i, part in enumerate(split_text(text)):
        sent.append(client.send_message(
            channel_id, part, bot_id=bot_id, reply_to=(reply_to if i == 0 else None) or None, safe_mentions=True,
        ))
    return {"ok": True, "channel_id": channel_id, "message": sent[0], "parts": len(sent)}
