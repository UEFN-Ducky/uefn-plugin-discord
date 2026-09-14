"""Discord automations tiles: contrib ids + send payload fallbacks."""

from __future__ import annotations

import json
from pathlib import Path
from . import automations


def test_plugin_json_declares_message_and_send() -> None:
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    auto = data["contributes"]["automations"]
    triggers = {row["id"] for row in auto["triggers"]}
    nodes = {row["id"] for row in auto["nodes"]}
    assert "discord.message" in triggers
    assert "discord.send" in nodes
    fields = {f["id"] for f in auto["nodes"][0]["config_fields"]}
    assert {"channel_id", "text"} <= fields
    tmpls = auto["templates"]
    ids = {row["id"] for row in tmpls}
    assert {"discord-spawn-ducky", "discord-spawn-ack"} <= ids
    spawn = next(row for row in tmpls if row["id"] == "discord-spawn-ducky")
    types = {n["type"] for n in spawn["graph"]["nodes"]}
    assert {"discord.message", "ducky.spawn"} <= types


def test_message_payload_aliases_prompt() -> None:
    out = automations.message_payload(
        {"id": "m1", "author": "Ada", "author_id": "9", "content": "hello"},
        "c1",
        "bot-a",
        {"guild_id": "g1", "id": "m1"},
    )
    assert out["channel_id"] == "c1"
    assert out["content"] == "hello"
    assert out["prompt"] == "hello"
    assert out["bot_id"] == "bot-a"
    assert out["guild_id"] == "g1"


def test_send_falls_back_to_payload(monkeypatch) -> None:
    sent: list[tuple] = []

    def fake_send(channel_id: str, text: str, *, bot_id: str | None = None):
        sent.append((channel_id, text, bot_id))
        return {"id": "out"}

    from . import client as real_client

    monkeypatch.setattr(real_client, "send_message", fake_send)
    out = automations.handle_send(
        {"config": {}, "payload": {"channel_id": "c9", "content": "hi", "bot_id": "b1"}}
    )
    assert out["ok"] is True
    assert sent == [("c9", "hi", "b1")]


def test_send_prefers_config_over_payload(monkeypatch) -> None:
    sent: list[tuple] = []

    def fake_send(channel_id: str, text: str, *, bot_id: str | None = None):
        sent.append((channel_id, text, bot_id))
        return {"id": "out"}

    from . import client as real_client

    monkeypatch.setattr(real_client, "send_message", fake_send)
    out = automations.handle_send(
        {
            "config": {"channel_id": "cfg", "text": "from-config"},
            "payload": {"channel_id": "pay", "content": "from-payload"},
        }
    )
    assert out["ok"] is True
    assert sent == [("cfg", "from-config", None)]


def test_send_requires_channel_and_text() -> None:
    assert automations.handle_send({"config": {}, "payload": {}})["ok"] is False
    assert automations.handle_send({"config": {"channel_id": "c"}, "payload": {}})["ok"] is False
