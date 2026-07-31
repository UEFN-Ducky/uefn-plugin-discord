"""Panel RPCs for Discord UI (Settings / Group Chat / plugin HTML).

Registered via ``api.register_panel_rpc``. Host ``PanelApi.discord_*`` methods
shim to ``plugin_call("discord", …)`` during the React → HTML cutover.
"""

from __future__ import annotations

from typing import Any


def _bot_id(bot_id: str | None = None) -> str:
    from . import bots

    return (bot_id or bots.DEFAULT_BOT_ID).strip() or bots.DEFAULT_BOT_ID


def _push(event: dict[str, Any]) -> None:
    try:
        from frontend.ui_web.verse_editor.panel_events import push_agent_event

        push_agent_event(event)
    except Exception:
        pass


def list_bots() -> dict[str, Any]:
    from . import bots

    return {"ok": True, "bots": bots.public_list()}


def save_bot(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    from . import bots, client, poller, presence

    p = patch if isinstance(patch, dict) else {}
    create = bool(p.get("create"))
    try:
        profile = bots.save_bot(
            bot_id=str(p.get("id") or p.get("bot_id") or "") or None,
            label=str(p["label"]) if "label" in p else None,
            guild_id=str(p["guild_id"]) if "guild_id" in p else None,
            post_as=str(p["post_as"]) if "post_as" in p else None,
            allowed_ids=str(p["allowed_ids"]) if "allowed_ids" in p else None,
            prefix=str(p["prefix"]) if "prefix" in p else None,
            enabled=bool(p["enabled"]) if "enabled" in p else None,
            show_offline=bool(p["show_offline"]) if "show_offline" in p else None,
            token=str(p.get("token") or "") or None,
            create=create or not (p.get("id") or p.get("bot_id")),
        )
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if profile.enabled and bots.get_token(profile.id):
        presence.bump_presence(profile.id)
        cid = bots.get_channel_id(profile.id)
        if cid:
            poller.ensure_watching(cid, bot_id=profile.id)
    else:
        poller.stop_bot(profile.id)
    _push({"type": "discord_changed"})
    status: dict[str, Any] = {
        "ok": True,
        "bot": {**profile.to_dict(), "has_token": bool(bots.get_token(profile.id))},
    }
    if bots.get_token(profile.id):
        status["status"] = client.bot_status(bot_id=profile.id)
    return status


def delete_bot(bot_id: str = "") -> dict[str, Any]:
    from . import bots, poller

    bid = _bot_id(bot_id)
    poller.stop_bot(bid)
    try:
        bots.delete_bot(bid)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _push({"type": "discord_changed"})
    return {"ok": True, "id": bid}


def status(bot_id: str = "") -> dict[str, Any]:
    from . import bots, client, poller, presence

    bid = _bot_id(bot_id)
    if not client.get_token(bid):
        return {
            "ok": False,
            "configured": False,
            "bot_id": bid,
            "error": "No bot token set",
            "post_name": bots.get_post_as(bid),
            "allowed_ids": bots.get_allowed_ids(bid),
            "prefix": bots.get_prefix(bid),
            "label": (bots.get_bot(bid) or bots.BotProfile(id=bid)).label,
        }
    st = client.bot_status(bot_id=bid)
    st["configured"] = True
    st["guild_set"] = bool(client.get_guild_id(bid))
    st["post_name"] = bots.get_post_as(bid)
    st["allowed_ids"] = bots.get_allowed_ids(bid)
    st["prefix"] = bots.get_prefix(bid)
    st["label"] = (bots.get_bot(bid) or bots.BotProfile(id=bid)).label
    st["enabled"] = bool((bots.get_bot(bid) or bots.BotProfile(id=bid)).enabled)
    if st.get("ok"):
        presence.ensure_started(bid)
        presence.ensure_all_enabled()
        poller.sync_enabled_bots()
        if st["guild_set"]:
            poller.ensure_watching(bots.get_channel_id(bid), bot_id=bid)
    return st


def list_channels(bot_id: str = "") -> dict[str, Any]:
    from . import client

    bid = _bot_id(bot_id)
    try:
        return {"ok": True, "bot_id": bid, "channels": client.list_channels(text_only=True, bot_id=bid)}
    except client.DiscordError as e:
        return {"ok": False, "bot_id": bid, "error": str(e)}


def debug(bot_id: str = "") -> dict[str, Any]:
    from . import client, poller

    bid = _bot_id(bot_id)
    state = poller.debug_state(bid)
    cid = str(state.get("watching_channel_id") or "")
    if cid:
        try:
            for ch in client.list_channels(text_only=True, bot_id=bid):
                if ch.get("id") == cid:
                    state["watching_channel_name"] = ch.get("name", "")
                    break
        except client.DiscordError:
            pass
    return state


def open_channel(channel_id: str = "", bot_id: str = "") -> dict[str, Any]:
    from . import bots, client, poller

    bid = _bot_id(bot_id)
    cid = str(channel_id or "").strip()
    if not cid:
        return {"ok": False, "error": "No channel id"}
    try:
        messages = client.fetch_messages(cid, limit=50, bot_id=bid)
    except client.DiscordError as e:
        return {"ok": False, "error": str(e)}
    newest = messages[-1]["id"] if messages else None
    poller.open_channel(cid, newest, bot_id=bid)
    bots.set_channel_id(bid, cid)
    return {"ok": True, "channel_id": cid, "bot_id": bid, "messages": messages}


def fetch_messages(
    channel_id: str = "",
    after: str = "",
    limit: int = 50,
    bot_id: str = "",
) -> dict[str, Any]:
    """UI live-refresh: messages newer than ``after`` (plugin-owned; no host push)."""
    from . import client

    bid = _bot_id(bot_id)
    cid = str(channel_id or "").strip()
    if not cid:
        return {"ok": False, "error": "No channel id", "messages": [], "bot_id": bid}
    after_id = str(after or "").strip() or None
    try:
        messages = client.fetch_messages(
            cid,
            after=after_id,
            limit=max(1, min(int(limit or 50), 100)),
            bot_id=bid,
        )
    except client.DiscordError as e:
        return {"ok": False, "error": str(e), "messages": [], "bot_id": bid, "channel_id": cid}
    return {
        "ok": True,
        "channel_id": cid,
        "bot_id": bid,
        "after": after_id or "",
        "messages": messages,
    }


def open_portal(bot_id: str = "") -> dict[str, Any]:
    import webbrowser

    from . import client

    bid = _bot_id(bot_id)
    url = "https://discord.com/developers/applications"
    try:
        app_id = client.application_id(bot_id=bid)
        if app_id:
            url = f"{url}/{app_id}/bot"
    except client.DiscordError:
        pass
    webbrowser.open(url)
    return {"ok": True, "url": url, "bot_id": bid}


def send(channel_id: str = "", text: str = "", bot_id: str = "") -> dict[str, Any]:
    from . import bots, client

    bid = _bot_id(bot_id)
    body = str(text or "")
    name = bots.get_post_as(bid)
    if name:
        body = f"**{name}:** {body}"
    try:
        msg = client.send_message(str(channel_id or ""), body, bot_id=bid)
        return {"ok": True, "message": msg, "bot_id": bid}
    except client.DiscordError as e:
        return {"ok": False, "error": str(e), "bot_id": bid}


def list_members(bot_id: str = "") -> dict[str, Any]:
    from . import client, presence

    bid = _bot_id(bot_id)
    gid = client.get_guild_id(bid) or ""
    if not client.get_token(bid):
        return {"ok": False, "error": "No bot token set", "groups": [], "bot_id": bid}
    presence.ensure_started(bid)
    snap = presence.snapshot(gid, bot_id=bid)
    if snap.get("ready") and snap.get("groups"):
        return snap
    try:
        members = client.list_guild_members(limit=100, bot_id=bid)
    except client.DiscordError as e:
        return {
            "ok": True,
            "guild_id": gid,
            "bot_id": bid,
            "groups": [],
            "ready": False,
            "error": str(e),
        }
    people = [
        {
            "id": m.get("id") or "",
            "name": (m.get("nick") or m.get("username") or "unknown"),
            "bot": bool(m.get("bot")),
            "status": "offline",
            "color": None,
        }
        for m in members
        if m.get("id")
    ]
    people.sort(key=lambda p: (p["name"] or "").lower())
    if not people:
        return {
            "ok": True,
            "guild_id": gid,
            "bot_id": bid,
            "groups": [],
            "ready": False,
            "error": "No members returned — enable Server Members Intent in the Dev Portal, then restart.",
        }
    return {
        "ok": True,
        "guild_id": gid,
        "bot_id": bid,
        "ready": True,
        "groups": [
            {
                "id": "members",
                "name": "Members",
                "count": len(people),
                "members": people,
            }
        ],
    }


def register_panel_rpcs(api: Any) -> None:
    api.register_panel_rpc("list_bots", list_bots)
    api.register_panel_rpc("save_bot", save_bot)
    api.register_panel_rpc("delete_bot", delete_bot)
    api.register_panel_rpc("status", status)
    api.register_panel_rpc("list_channels", list_channels)
    api.register_panel_rpc("debug", debug)
    api.register_panel_rpc("open_channel", open_channel)
    api.register_panel_rpc("fetch_messages", fetch_messages)
    api.register_panel_rpc("open_portal", open_portal)
    api.register_panel_rpc("send", send)
    api.register_panel_rpc("list_members", list_members)
    api.log("Discord panel RPCs registered")
