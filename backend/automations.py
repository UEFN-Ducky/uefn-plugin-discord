"""Automations tiles: Gateway emit + discord.send handler."""

from __future__ import annotations

from typing import Any

_api: Any = None


def register_nodes(api: Any) -> None:
    """Register discord.send. Skip quietly on hosts without the automations plane."""
    global _api
    _api = api
    if not hasattr(api, "register_automation_node"):
        return
    api.register_automation_node("discord.send", handle_send)


def clear_api() -> None:
    global _api
    _api = None


def message_payload(msg: dict[str, Any], channel_id: str, bot_id: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    content = str((msg or {}).get("content") or "")
    data = raw if isinstance(raw, dict) else {}
    return {
        "channel_id": str(channel_id or "").strip(),
        "message_id": str(msg.get("id") or data.get("id") or ""),
        "guild_id": str(data.get("guild_id") or ""),
        "bot_id": str(bot_id or ""),
        "author": str(msg.get("author") or ""),
        "author_id": str(msg.get("author_id") or ""),
        "content": content,
        "prompt": content,
    }


def emit_message(msg: dict[str, Any], channel_id: str, bot_id: str, raw: dict[str, Any] | None = None) -> None:
    api = _api
    if api is None or not hasattr(api, "emit_automation"):
        return
    api.emit_automation("discord.message", message_payload(msg, channel_id, bot_id, raw))


def handle_send(ctx: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    payload = ctx.get("payload") if isinstance(ctx.get("payload"), dict) else {}
    channel_id = str(cfg.get("channel_id") or payload.get("channel_id") or "").strip()
    text = str(cfg.get("text") or payload.get("content") or payload.get("text") or "").strip()
    bot_id = str(cfg.get("bot_id") or payload.get("bot_id") or "").strip() or None
    if not channel_id:
        return {"ok": False, "error": "channel_id required"}
    if not text:
        return {"ok": False, "error": "text required"}
    from . import client

    sent = client.send_message(channel_id, text, bot_id=bot_id)
    return {"ok": True, "channel_id": channel_id, "message": sent}
