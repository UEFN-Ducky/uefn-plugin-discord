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
    send_spec = next(row for row in auto["nodes"] if row["id"] == "discord.send")
    fields = {f["id"] for f in send_spec["config_fields"]}
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

    def fake_send(channel_id: str, text: str, *, bot_id: str | None = None, **_kw):
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

    def fake_send(channel_id: str, text: str, *, bot_id: str | None = None, **_kw):
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


def test_payload_mention_allowed_and_pr_link(monkeypatch) -> None:
    monkeypatch.setattr(automations, "_bot_user_id", lambda _bid: "42")
    monkeypatch.setattr(automations, "_is_allowed", lambda aid, _bid: aid == "9")
    out = automations.message_payload(
        {"id": "m1", "author": "Lezzy", "author_id": "9",
         "content": "<@42> https://github.com/UEFN-Ducky/UEFN-Ducky/pull/7"},
        "c1", "bob", {"mentions": [{"id": "42"}]},
    )
    assert out["mentioned"] == "yes" and out["allowed"] == "yes"
    assert out["role_ids"] == []  # no member block (a DM): no roles
    with_roles = automations.message_payload({"id": "m3", "author_id": "7", "content": "hi"}, "c1", "bob",
                                             {"member": {"roles": [111, "222"]}})
    assert with_roles["role_ids"] == ["111", "222"] and with_roles["allowed"] == "no"
    assert out["prompt"] == "https://github.com/UEFN-Ducky/UEFN-Ducky/pull/7"
    assert (out["pr_owner"], out["pr_repo"], out["pr_number"]) == ("UEFN-Ducky", "UEFN-Ducky/UEFN-Ducky", "7")
    other = automations.message_payload(
        {"id": "m2", "author_id": "8", "content": "see http://github.com/x/y/pull/1 or github.com.evil.io/a/b/pull/2"},
        "c1", "bob", {},
    )
    assert other["mentioned"] == "no" and other["allowed"] == "no"
    assert other["pr_url"] == "" and other["pr_owner"] == ""


def test_send_wired_text_replies_split_and_safe(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_send(channel_id: str, text: str, **kw):
        calls.append({"channel_id": channel_id, "text": text, **kw})
        return {"id": "out"}

    from . import client as real_client

    monkeypatch.setattr(real_client, "send_message", fake_send)
    long_text = ("line\n" * 600).strip()
    out = automations.handle_send({
        "config": {"text": "ignored"},
        "inputs": {"text": long_text},
        "payload": {"channel_id": "c1", "message_id": "m1", "content": "@bob review"},
    })
    assert out["ok"] is True and out["parts"] == len(calls) > 1
    assert all(len(c["text"]) <= 2000 and c["safe_mentions"] for c in calls)
    assert calls[0]["reply_to"] == "m1" and calls[1]["reply_to"] is None
    assert "".join(c["text"] for c in calls).count("line") == 600


def test_pr_review_template_gates_and_wires() -> None:
    root = Path(__file__).resolve().parents[1]
    auto = json.loads((root / "plugin.json").read_text(encoding="utf-8"))["contributes"]["automations"]
    tmpl = next(row for row in auto["templates"] if row["id"] == "discord-pr-review")
    nodes = {n["id"]: n for n in tmpl["graph"]["nodes"]}
    assert nodes["t"]["config"] == {"mentioned": "yes", "allowed": "yes"}
    assert nodes["b"]["config"] == {"field": "pr_owner", "equals": "UEFN-Ducky"}
    assert "--match-head-commit" in nodes["a"]["config"]["prompt"]
    assert {"source": "a", "target": "r", "kind": "data", "source_pin": "text", "target_pin": "text"} in tmpl["graph"]["edges"]
    send = next(row for row in auto["nodes"] if row["id"] == "discord.send")
    assert [p["id"] for p in send["inputs"]] == ["text"]


def test_react_swaps_eyes_for_check(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_react(channel_id, message_id, emoji, *, remove=False, bot_id=None):
        calls.append((channel_id, message_id, emoji, remove))
        return {"ok": True}

    from . import client as real_client

    monkeypatch.setattr(real_client, "react", fake_react)
    out = automations.handle_react({"config": {"emoji": "✅", "remove": "👀"},
                                    "payload": {"channel_id": "c1", "message_id": "m1"}})
    assert out["ok"] is True
    assert calls == [("c1", "m1", "👀", True), ("c1", "m1", "✅", False)]
    assert automations.handle_react({"config": {"emoji": "x"}, "payload": {}})["ok"] is False


def test_emit_runs_workflows_once_per_message(monkeypatch, tmp_path) -> None:
    from . import commands

    monkeypatch.setattr(commands, "_claims_dir", lambda: tmp_path)
    monkeypatch.setattr(automations, "_bot_user_id", lambda _bid: "")
    monkeypatch.setattr(automations, "_is_allowed", lambda *_a: False)
    emitted: list[str] = []

    class Api:
        def emit_automation(self, trigger, payload):
            emitted.append(payload["message_id"])

    monkeypatch.setattr(automations, "_api", Api())
    msg = {"id": "dup-1", "author_id": "1", "content": "https://github.com/UEFN-Ducky/x/pull/1"}
    for _ in range(5):  # five processes / gateway copies hear the same message
        automations.emit_message(msg, "c1", "bob", {})
    automations.emit_message(msg, "c1", "other-bot", {})  # another bot runs its own workflows
    assert emitted == ["dup-1", "dup-1"]
    assert commands._claim_message("dup-1")  # the same message can still be a !command


def test_send_requires_channel_and_text() -> None:
    assert automations.handle_send({"config": {}, "payload": {}})["ok"] is False
    assert automations.handle_send({"config": {"channel_id": "c"}, "payload": {}})["ok"] is False
