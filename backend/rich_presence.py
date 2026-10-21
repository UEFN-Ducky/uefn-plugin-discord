"""Discord Rich Presence — "Playing Ducky" on the user's own Discord profile.

Talks to the Discord desktop client over its local IPC pipe (``discord-ipc-N``), not
the bot Gateway: bots can't show Rich Presence. Shows whether UEFN is open, how many
duckies are working and the session timer. Never project names or chat titles: the
presence is public.

The application, image and button are fixed (the official Ducky app); users only pick
what is shown.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from frontend.atomic_json import read_json_object, write_json_atomic
from frontend.settings import default_app_data_dir

_OP_HANDSHAKE = 0
_OP_FRAME = 1
_OP_CLOSE = 2
_TICK_S = 15.0
_RETRY_S = 30.0
# Official Ducky Discord application (not a secret); its Art Assets hold LARGE_IMAGE.
OFFICIAL_APP_ID = "1562529897266675712"
LARGE_IMAGE = "ducky_1024"
BUTTONS = [{"label": "UEFN Ducky", "url": "https://uefnducky.org"}]
# What the user can switch, and the default for each (all on: nothing shown is private).
TOGGLES = {"enabled": True, "show_uefn": True, "show_duckies": True}

_lock = threading.Lock()
_wake = threading.Event()
_thread: threading.Thread | None = None
_running = False
_started_at = int(time.time())
_state: dict[str, Any] = {"connected": False, "error": "", "user": "", "activity": None}


# ---- settings ----------------------------------------------------------------


def _settings_path() -> Path:
    return default_app_data_dir() / "discord_rich_presence.json"


def _read_cfg() -> dict[str, Any]:
    data = read_json_object(_settings_path())
    return data if isinstance(data, dict) else {}


def _toggles(cfg: dict[str, Any]) -> dict[str, bool]:
    return {k: bool(cfg.get(k, default)) for k, default in TOGGLES.items()}


def public_settings() -> dict[str, Any]:
    cfg = _read_cfg()
    return {"ok": True, **_toggles(cfg), **status()}


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cfg = _read_cfg()
    for key in TOGGLES:
        if key in patch:
            cfg[key] = bool(patch[key])
    write_json_atomic(_settings_path(), cfg)
    with _lock:
        _state["activity"] = None
    _wake.set()
    return public_settings()


def status() -> dict[str, Any]:
    with _lock:
        return {
            "connected": bool(_state["connected"]),
            "error": str(_state["error"] or ""),
            "discord_user": str(_state["user"] or ""),
        }


# ---- what Ducky is doing -----------------------------------------------------


def _running_duckies() -> int:
    try:
        from frontend.ui_web.agent_modes import list_running_agents

        return len(list_running_agents())
    except Exception:
        return 0


def _uefn_open() -> bool:
    # The UEFN listener's health answer: one loopback GET per tick, where a process list
    # would start tasklist twice every 15 s for as long as Discord is open.
    try:
        from backend.bridge import listener_get_health
        from frontend.settings import PANEL_LISTENER_PORT

        health = listener_get_health(PANEL_LISTENER_PORT, timeout=0.5)
        return bool(health is not None and health.get("status") == "ok")
    except Exception:
        return False


def _app_version() -> str:
    try:
        from frontend import __version__

        return str(__version__)
    except Exception:
        return ""


def _current_facts(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "duckies": _running_duckies(),
        "uefn_open": _uefn_open() if _toggles(cfg)["show_uefn"] else False,
        "version": _app_version(),
    }


def build_activity(cfg: dict[str, Any], *, duckies: int, uefn_open: bool = False, version: str = "") -> dict[str, Any]:
    show = _toggles(cfg)
    details = "Editing in UEFN" if show["show_uefn"] and uefn_open else "Building with Ducky"
    activity: dict[str, Any] = {
        "type": 0,
        "details": details,
        "timestamps": {"start": _started_at},
        "assets": {"large_image": LARGE_IMAGE, "large_text": f"UEFN Ducky {version}".strip()},
        "buttons": BUTTONS,
    }
    if show["show_duckies"]:
        if duckies == 1:
            activity["state"] = "🦆 1 ducky working"
        elif duckies > 1:
            activity["state"] = f"🦆 {duckies} duckies working"
        else:
            activity["state"] = "💤 Duckies resting"
    return activity


# ---- IPC ---------------------------------------------------------------------


class _Ipc:
    def __init__(self) -> None:
        self._pipe: Any = None

    def connect(self, app_id: str) -> dict[str, Any]:
        last: Exception | None = None
        for n in range(10):
            try:
                self._pipe = _open_pipe(n)
                break
            except OSError as exc:
                last = exc
        if self._pipe is None:
            raise ConnectionError("Discord desktop app isn't running") from last
        self._send(_OP_HANDSHAKE, {"v": 1, "client_id": app_id})
        op, data = self._recv()
        if op == _OP_CLOSE or data.get("evt") == "ERROR":
            self.close()
            msg = str(data.get("message") or (data.get("data") or {}).get("message") or "rejected")
            raise ConnectionError(f"Discord refused the App ID: {msg}")
        return data

    def set_activity(self, activity: dict[str, Any] | None) -> dict[str, Any]:
        self._send(
            _OP_FRAME,
            {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": activity}, "nonce": uuid.uuid4().hex},
        )
        _op, data = self._recv()
        if data.get("evt") == "ERROR":
            raise RuntimeError(str((data.get("data") or {}).get("message") or "SET_ACTIVITY failed"))
        return data

    def close(self) -> None:
        pipe, self._pipe = self._pipe, None
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass

    def _send(self, op: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._pipe.write(struct.pack("<II", op, len(body)) + body)
        self._pipe.flush()

    def _recv(self) -> tuple[int, dict[str, Any]]:
        head = self._read_exact(8)
        op, length = struct.unpack("<II", head)
        body = self._read_exact(length)
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            data = {}
        return op, data if isinstance(data, dict) else {}

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._pipe.read(n - len(buf))
            if not chunk:
                raise ConnectionError("Discord closed the connection")
            buf += chunk
        return buf


def _open_pipe(n: int) -> Any:
    if sys.platform == "win32":
        return open(rf"\\?\pipe\discord-ipc-{n}", "r+b", buffering=0)
    import socket

    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(os.path.join(base, f"discord-ipc-{n}"))
    return sock.makefile("rwb", buffering=0)


# ---- worker ------------------------------------------------------------------


def _set_state(**kw: Any) -> None:
    with _lock:
        _state.update(kw)


def _loop() -> None:
    ipc = _Ipc()
    connected = False
    next_try = 0.0
    while _running:
        cfg = _read_cfg()
        if not _toggles(cfg)["enabled"]:
            if connected:
                _disconnect(ipc)
                connected = False
            next_try = 0.0
            _set_state(error="")
        else:
            try:
                if not connected and time.monotonic() >= next_try:
                    ready = ipc.connect(OFFICIAL_APP_ID)
                    connected = True
                    user = (ready.get("data") or {}).get("user") or {}
                    _set_state(connected=True, error="", user=str(user.get("username") or ""), activity=None)
                if connected:
                    activity = build_activity(cfg, **_current_facts(cfg))
                    with _lock:
                        changed = activity != _state["activity"]
                    if changed:
                        ipc.set_activity(activity)
                        _set_state(activity=activity)
            except Exception as exc:
                ipc.close()
                connected = False
                next_try = time.monotonic() + _RETRY_S
                _set_state(connected=False, error=str(exc), activity=None)
        _wake.wait(_TICK_S)
        _wake.clear()
    _disconnect(ipc)


def _disconnect(ipc: _Ipc) -> None:
    try:
        ipc.set_activity(None)
    except Exception:
        pass
    ipc.close()
    _set_state(connected=False, activity=None, user="")


def start() -> None:
    global _thread, _running
    if _thread is not None and _thread.is_alive():
        _wake.set()
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="discord-rich-presence")
    _thread.start()


def stop(join_timeout_s: float = 2.0) -> None:
    global _thread, _running
    _running = False
    _wake.set()
    t, _thread = _thread, None
    if t is not None:
        t.join(timeout=join_timeout_s)


def refresh() -> None:
    """Re-check now (e.g. a ducky just started or stopped)."""
    _wake.set()
