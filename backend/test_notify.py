"""Job-done Discord webhook: only agent_stopped (done/error/timeout), configurable URL."""

from __future__ import annotations

from pathlib import Path

import pytest

from . import notify


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("frontend.settings.default_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(notify, "default_app_data_dir", lambda: tmp_path)
    store: dict[str, str] = {}

    def get_key(provider: str) -> str:
        return store.get(provider) or ""

    def set_key(provider: str, value: str) -> None:
        v = (value or "").strip()
        if v:
            store[provider] = v
        else:
            store.pop(provider, None)

    def clear_key(provider: str) -> None:
        store.pop(provider, None)

    monkeypatch.setattr(notify, "_secret_get", get_key)
    monkeypatch.setattr(notify, "_secret_set", set_key)
    monkeypatch.setattr(notify, "_secret_clear", clear_key)
    notify._seen.clear()
    yield tmp_path, store


def test_skips_when_disabled_or_no_webhook(isolated):
    _tmp, store = isolated
    notify.save_settings(enabled=False, mention_id="", webhook_url="")
    assert notify.payload_for_event({"type": "agent_stopped", "reason": "done", "conv_id": "c1", "run_id": "r1"}) is None
    notify.save_settings(enabled=True, mention_id="", webhook_url="")
    assert notify.payload_for_event({"type": "agent_stopped", "reason": "done", "conv_id": "c1", "run_id": "r1"}) is None
    store[notify.WEBHOOK_SECRET] = "https://discord.com/api/webhooks/1/abc"
    notify.save_settings(enabled=True, mention_id="42", webhook_url=None)
    assert notify.payload_for_event({"type": "assistant_done", "conv_id": "c1"}) is None
    assert notify.payload_for_event({"type": "agent_stopped", "reason": "cancelled", "conv_id": "c1", "run_id": "r1"}) is None


def test_builds_payload_on_job_end(isolated):
    _tmp, store = isolated
    url = "https://discord.com/api/webhooks/1/abc"
    notify.save_settings(enabled=True, mention_id="99", webhook_url=url)
    body = notify.payload_for_event(
        {
            "type": "agent_stopped",
            "reason": "done",
            "conv_id": "c1",
            "run_id": "r1",
        },
        title="Verse Coder",
        preview="fixed the trigger",
    )
    assert body is not None
    assert "<@99>" in body["content"]
    assert "Verse Coder" in body["content"]
    assert "fixed the trigger" in body["content"]
    assert body["allowed_mentions"]["users"] == ["99"]


def test_rejects_non_discord_webhook_url(isolated):
    with pytest.raises(ValueError):
        notify.save_settings(enabled=True, mention_id="", webhook_url="https://evil.example/hook")


def test_dedupes_double_push_same_run(isolated):
    notify.save_settings(
        enabled=True,
        mention_id="",
        webhook_url="https://discord.com/api/webhooks/1/abc",
    )
    ev = {"type": "agent_stopped", "reason": "done", "conv_id": "c1", "run_id": "same"}
    assert notify.payload_for_event(ev, title="A") is not None
    assert notify.payload_for_event(ev, title="A") is None
