"""The bots' gateway, poller and Discord presence start only in the app window."""

from __future__ import annotations

import importlib
import sys
import threading
import types
from typing import Any

import pytest

plugin = importlib.import_module(__package__ or "backend")


def _with_role(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    fake = types.ModuleType("backend.process_role")
    fake.role = lambda: role  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backend.process_role", fake)


class _Api:
    def register_panel_rpc(self, *_a: Any, **_k: Any) -> None: ...

    def is_enabled(self) -> bool:
        return True

    def log(self, _msg: str) -> None: ...


@pytest.fixture()
def started(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    names: list[str] = []
    # Fakes for the modules register() imports (tools needs the app's core on the path).
    for sub, attrs in {"tools": {"register_tools": lambda api: None},
                       "automations": {"register_nodes": lambda api: None},
                       "panel_rpc": {"register_panel_rpcs": lambda api: None},
                       "notify": {"install_hook": lambda: None}}.items():
        mod = types.ModuleType(f"{plugin.__name__}.{sub}")
        for name, fn in attrs.items():
            setattr(mod, name, fn)
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        monkeypatch.setattr(plugin, sub, mod, raising=False)
    monkeypatch.setattr(threading.Thread, "start", lambda self: names.append(self.name))
    return names


@pytest.mark.parametrize("role", ["tool_server", "agent_host"])
def test_no_runtime_outside_the_app(role: str, monkeypatch: pytest.MonkeyPatch, started: list[str]) -> None:
    _with_role(monkeypatch, role)
    plugin.register(_Api())
    assert "discord-runtime-start" not in started


def test_one_runtime_in_the_app(monkeypatch: pytest.MonkeyPatch, started: list[str]) -> None:
    _with_role(monkeypatch, "app")
    plugin.register(_Api())
    assert started.count("discord-runtime-start") == 1


def test_old_core_falls_back_to_the_bridge_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "backend.process_role", None)  # import raises ImportError
    monkeypatch.setenv("UEFN_DUCKY_MCP_BRIDGE", "1")
    assert plugin._in_app() is False
    monkeypatch.delenv("UEFN_DUCKY_MCP_BRIDGE")
    assert plugin._in_app() is True
