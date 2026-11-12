import sys
import types

import pytest

from backend.host import host


def _fake(monkeypatch, name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


def test_new_layout_wins_over_old(monkeypatch):
    _fake(monkeypatch, "frontend.ui_web.chats.conversations", create_conversation="new")
    _fake(monkeypatch, "frontend.ui_web.project_chats", create_conversation="old")
    assert host("create_conversation") == "new"


def test_old_app_still_works(monkeypatch):
    for gone in ("frontend.ui_web.chats.conversations", "frontend.ui_web.agent_turns.routing"):
        monkeypatch.setitem(sys.modules, gone, None)  # None in sys.modules = ImportError
    _fake(monkeypatch, "frontend.ui_web.agent_modes", run_message_and_wait="old")
    assert host("run_message_and_wait") == "old"


def test_missing_name_raises_import_error():
    with pytest.raises(ImportError):
        host("no_such_function_anywhere")
