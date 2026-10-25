"""Automations tiles: Gateway emit + discord.send handler."""

from __future__ import annotations

import re
from typing import Any

_api: Any = None

# A GitHub pull request link: owner/repo + number. Only github.com, https only.
_PR_LINK = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/(\d+)\b")
_CHUNK = 1900  # Discord's cap is 2000 per message


def register_nodes(api: Any) -> None:
    """Register discord.send. Skip quietly on hosts without the automations plane."""
    global _api
    _api = api
    if not hasattr(api, "register_automation_node"):
        return
    api.register_automation_node("discord.send", handle_send)
    # Not a step: fills the "Bot" dropdowns (options_from) with this PC's bots.
    api.register_automation_node("discord.bots", bot_options)


def clear_api() -> None:
    global _api
    _api = None


def bot_options(_ctx: Any = None) -> list[dict[str, str]]:
    from . import bots

    return [{"id": b.id, "label": b.label} for b in bots.list_bots()]


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
        "pr_url": pr.group(0) if pr else "",
        "pr_repo": pr.group(1) if pr else "",
        "pr_owner": pr.group(1).split("/")[0] if pr else "",
        "pr_number": pr.group(2) if pr else "",
    }


def emit_message(msg: dict[str, Any], channel_id: str, bot_id: str, raw: dict[str, Any] | None = None) -> None:
    api = _api
    if api is None or not hasattr(api, "emit_automation"):
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
