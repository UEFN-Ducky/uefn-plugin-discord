"""Notify Discord via Incoming Webhook when a Ducky app job ends.

Listens for panel ``agent_stopped`` (done / error / timeout). Cancelled turns
are skipped. Webhook URL is a secret — not the bot token.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from frontend.atomic_json import read_json_object, write_json_atomic
from frontend.settings import default_app_data_dir

WEBHOOK_SECRET = "discord_notify_webhook"
_MAX_CONTENT = 1900
_SEEN_TTL_S = 120.0
_WEBHOOK_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
    "https://ptb.discord.com/api/webhooks/",
    "https://canary.discord.com/api/webhooks/",
)

_lock = threading.Lock()
_seen: dict[str, float] = {}
_orig_resolve = None


def _settings_path():
    return default_app_data_dir() / "discord_notify.json"


def _read_cfg() -> dict[str, Any]:
    data = read_json_object(_settings_path())
    return data if isinstance(data, dict) else {}


def _secret_get(key: str) -> str:
    from backend.agent.secrets import get_key

    return (get_key(key) or "").strip()


def _secret_set(key: str, value: str) -> None:
    from backend.agent.secrets import set_key

    set_key(key, value)


def _secret_clear(key: str) -> None:
    from backend.agent.secrets import clear_key

    clear_key(key)


def webhook_url() -> str:
    return _secret_get(WEBHOOK_SECRET)


def is_webhook_url(url: str) -> bool:
    u = (url or "").strip()
    return any(u.startswith(p) for p in _WEBHOOK_PREFIXES)


def public_settings() -> dict[str, Any]:
    cfg = _read_cfg()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "mention_id": str(cfg.get("mention_id") or "").strip(),
        "has_webhook": bool(webhook_url()),
    }


def save_settings(
    *,
    enabled: bool | None = None,
    mention_id: str | None = None,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    if webhook_url is not None:
        raw = str(webhook_url).strip()
        if raw and not is_webhook_url(raw):
            raise ValueError(
                "Webhook URL must be a Discord Incoming Webhook "
                "(https://discord.com/api/webhooks/…)"
            )
    cfg = _read_cfg()
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if mention_id is not None:
        cfg["mention_id"] = str(mention_id).strip()
    write_json_atomic(_settings_path(), cfg)
    if webhook_url is not None:
        raw = str(webhook_url).strip()
        if not raw:
            _secret_clear(WEBHOOK_SECRET)
        else:
            _secret_set(WEBHOOK_SECRET, raw)
    return public_settings()


def _prune_seen(now: float) -> None:
    dead = [k for k, ts in _seen.items() if now - ts > _SEEN_TTL_S]
    for k in dead:
        _seen.pop(k, None)


def _claim_run(conv_id: str, run_id: str) -> bool:
    key = f"{conv_id}:{run_id}"
    now = time.time()
    with _lock:
        _prune_seen(now)
        if key in _seen:
            return False
        _seen[key] = now
        return True


def payload_for_event(
    event: dict[str, Any],
    *,
    title: str = "",
    preview: str = "",
) -> dict[str, Any] | None:
    """Return Discord webhook JSON, or None if this event should not notify."""
    cfg = _read_cfg()
    if not cfg.get("enabled"):
        return None
    if not webhook_url():
        return None
    if str(event.get("type") or "") != "agent_stopped":
        return None
    reason = str(event.get("reason") or "")
    if reason not in ("done", "error", "timeout"):
        return None
    conv_id = str(event.get("conv_id") or "").strip()
    run_id = str(event.get("run_id") or "").strip()
    if not conv_id or not run_id:
        return None
    if not _claim_run(conv_id, run_id):
        return None
    name = (title or "").strip() or "Ducky"
    mention = str(cfg.get("mention_id") or "").strip()
    if reason == "done":
        line = f"🦆 **{name}** finished its job."
    else:
        line = f"🦆 **{name}** ended ({reason})."
    if mention:
        line = f"<@{mention}> {line}"
    extra = (preview or "").strip()
    if not extra and reason != "done":
        extra = str(event.get("detail") or "").strip()
    content = f"{line}\n{extra}".strip() if extra else line
    body: dict[str, Any] = {"content": content[:_MAX_CONTENT]}
    if mention:
        body["allowed_mentions"] = {"users": [mention]}
    return body


def _label_for(conv_id: str) -> str:
    try:
        from frontend.ui_web.project_chats import load_conversation

        conv = load_conversation(conv_id)
        return str(getattr(conv, "title", "") or "").strip() or "Ducky"
    except Exception:
        return "Ducky"


def _preview_for(event: dict[str, Any], conv_id: str) -> str:
    reason = str(event.get("reason") or "")
    if reason != "done":
        return str(event.get("detail") or reason)
    try:
        from frontend.ui_web.agent_modes import _last_assistant_text
        from frontend.ui_web.project_chats import load_conversation

        conv = load_conversation(conv_id)
        return str(_last_assistant_text(conv) if conv else "")[:400]
    except Exception:
        return ""


def post_webhook(url: str, body: dict[str, Any]) -> None:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "UEFN-Ducky-Discord-plugin",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        resp.read()


def on_panel_event(event: dict[str, Any]) -> None:
    if not isinstance(event, dict):
        return
    conv_id = str(event.get("conv_id") or "").strip()
    body = payload_for_event(
        event,
        title=_label_for(conv_id) if conv_id else "",
        preview=_preview_for(event, conv_id) if conv_id else "",
    )
    if body is None:
        return
    url = webhook_url()
    threading.Thread(
        target=_post_safe,
        args=(url, body),
        daemon=True,
        name="discord-job-webhook",
    ).start()


def _post_safe(url: str, body: dict[str, Any]) -> None:
    try:
        post_webhook(url, body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        pass


def install_hook() -> None:
    """Wrap panel push so every app job-end event can notify. Idempotent."""
    global _orig_resolve
    from frontend.ui_web import agent_modes

    if _orig_resolve is None:
        _orig_resolve = agent_modes._resolve_push

    def wrapped(push=None):
        inner = _orig_resolve(push)
        if getattr(inner, "_discord_job_notify", False):
            return inner

        def tap(event: dict[str, Any]) -> None:
            inner(event)
            try:
                on_panel_event(event)
            except Exception:
                pass

        tap._discord_job_notify = True  # type: ignore[attr-defined]
        return tap

    agent_modes._resolve_push = wrapped


def uninstall_hook() -> None:
    global _orig_resolve
    if _orig_resolve is None:
        return
    try:
        from frontend.ui_web import agent_modes

        agent_modes._resolve_push = _orig_resolve
    except Exception:
        pass
    _orig_resolve = None
