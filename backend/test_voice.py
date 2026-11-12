"""Offline tests for the voice helpers and the !bob builtins (no Discord, no audio)."""

from __future__ import annotations

from . import commands, voice


def test_parse_join_args():
    assert voice.parse_join_args("openai verse coder") == ("openai", "verse coder")
    assert voice.parse_join_args("LOCAL") == ("local", "")
    assert voice.parse_join_args("") == ("", "")
    assert voice.parse_join_args("verse") == ("", "verse")


def test_spoken_text_strips_markdown_and_caps():
    assert voice.spoken_text("**Hi** see `x` https://a.b ```py\nprint()\n```") == "Hi see x a link (code posted in chat)"
    long = "Word. " * 400
    assert len(voice.spoken_text(long)) <= 800


def test_sentences_split_for_fast_first_audio():
    assert voice.sentences("Oh nice! That works. Ok. Want more?") == ["Oh nice!", "That works. Ok.", "Want more?"]
    assert voice.sentences("") == []


def test_speak_queues_in_order(monkeypatch):
    s = voice._Session("default", "", "local", {})  # noqa: SLF001
    sent = []
    monkeypatch.setattr(s, "_tts", lambda t: f"/tmp/{t[:3]}.wav")
    monkeypatch.setattr(s, "send", lambda **kw: sent.append(kw["path"]))
    s.speak("First one here. Second one here. Third one here.")
    assert sent == ["/tmp/Fir.wav", "/tmp/Sec.wav", "/tmp/Thi.wav"]


def test_wake_word():
    w = ["bob"]
    assert voice.heard_for_bob("Hey, Bob! What's in my level?", w, False) == "What's in my level?"
    assert voice.heard_for_bob("bob", w, False) == ""  # just called -> "Yeah?"
    assert voice.heard_for_bob("did you eat lunch", w, False) is None  # not for BoB
    assert voice.heard_for_bob("and make it red", w, True) == "and make it red"  # still talking with him
    assert voice.heard_for_bob("bobcat facts", w, False) is None  # whole word only
    assert voice.heard_for_bob("anything", [], False) == "anything"  # wake off
    assert voice.heard_for_bob("Okay, Ducky, build it", ["okay ducky"], False) == "build it"


def test_wake_setting_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "_base", lambda: tmp_path)
    assert voice.load_wake() == [voice.DEFAULT_WAKE]
    voice.save_engine("local")
    assert voice.save_wake("Jarvis, hey bob") == ["jarvis", "hey bob"]
    assert voice.load_engine() == "local"  # saving one setting keeps the other
    assert voice.save_wake("off") == []


def test_noise_filter():
    assert voice.is_noise(" Thank you. ") and voice.is_noise("")
    assert not voice.is_noise("build my level")


def test_show_phrase():
    assert voice._SHOW_RE.search("hey bob show me the screen")  # noqa: SLF001
    assert voice._SHOW_RE.search("what's on my screen")  # noqa: SLF001
    assert not voice._SHOW_RE.search("show time")  # noqa: SLF001


def test_only_allow_list_reaches_the_agent():
    lines = [("1", "Owner", "build it"), ("2", "Guest", "delete everything"), ("", "Unknown", "hi")]
    owners, guests = voice.split_by_access(lines, {"1"})
    assert [l[0] for l in owners] == ["1"]
    assert [l[0] for l in guests] == ["2", ""]
    owners, guests = voice.split_by_access(lines, set())  # locked → nobody runs agents
    assert owners == [] and len(guests) == 3


def test_invite_code():
    assert commands.invite_code("https://discord.gg/AbC-12") == "AbC-12"
    assert commands.invite_code("join me https://discord.com/invite/xyz99 pls") == "xyz99"
    assert commands.invite_code("no link here") == ""


def test_voice_invite_joins_only_for_allow_list(monkeypatch):
    from . import client

    joined = []
    monkeypatch.setattr(commands, "allowed_ids", lambda bid=None: {"me"})
    monkeypatch.setattr(commands, "_claim_message", lambda *a, **k: True)
    monkeypatch.setattr(commands, "_send", lambda *a, **k: None)
    monkeypatch.setattr(commands.bots, "get_guild_id", lambda bid=None: "g1")
    monkeypatch.setattr(
        client, "resolve_invite",
        lambda code, bot_id=None: {"guild_id": "g1", "channel_id": "vc9", "channel_type": 2, "channel": "Meeting"},
    )
    monkeypatch.setattr(voice, "join", lambda **kw: joined.append(kw) or {"ok": True, "engine": "openai"})
    # Run the thread target inline.
    monkeypatch.setattr(commands.threading, "Thread", lambda target, args, **k: type("T", (), {"start": lambda s: target(*args)})())

    msg = {"id": "1", "author_id": "stranger", "content": "https://discord.gg/abc"}
    assert not commands._maybe_voice_invite(msg, msg["content"], "dm1", "default")  # noqa: SLF001
    assert joined == []
    msg["author_id"] = "me"
    assert commands._maybe_voice_invite(msg, msg["content"], "dm1", "default")  # noqa: SLF001
    assert joined == [{"bot_id": "default", "voice_channel_id": "vc9", "text_channel_id": "dm1"}]


def test_builtin_join_routes_to_voice(monkeypatch):
    seen = {}
    sent = []
    monkeypatch.setattr(voice, "join", lambda **kw: seen.update(kw) or {"ok": True, "engine": "local"})
    monkeypatch.setattr(commands, "_send", lambda cid, text, bid="default": sent.append(text))
    assert commands._run_builtin("join local verse", "c1", "default", "!bob", "u9")  # noqa: SLF001
    assert seen == {"bot_id": "default", "user_id": "u9", "text_channel_id": "c1", "engine": "local", "ducky": "verse"}
    assert "Joining" in sent[0]
    assert not commands._run_builtin("verse fix it", "c1", "default", "!bob", "u9")  # noqa: SLF001


def test_status_lists_live_calls(monkeypatch):
    s = voice._Session("b1", "", "local", {"name": "Verse Coder"})  # noqa: SLF001
    s.channel, s.state, s.conv_id = "Meeting", "in call", "c1"
    monkeypatch.setattr(voice, "_sessions", {"b1": s})
    assert voice.status() == [{"bot_id": "b1", "ducky": "Verse Coder", "engine": "local",
                               "channel": "Meeting", "state": "in call", "conv_id": "c1"}]
    s.closed = True
    assert voice.status() == []


def test_hush_stops_audio_queue_and_the_answer(monkeypatch):
    from . import host as host_mod

    s = voice._Session("b1", "", "local", {})  # noqa: SLF001
    s.conv_id = "c1"
    sent, cancelled = [], []
    monkeypatch.setattr(s, "send", lambda **kw: sent.append(kw))
    monkeypatch.setattr(host_mod, "host", lambda name: cancelled.append if name == "cancel_agent" else None)
    s.heard.put({"text": "old"})
    s.hush()
    assert {"cmd": "stop"} in sent and s.heard.empty() and cancelled == ["c1"]

    sent.clear()
    gen = s.hush_gen - 1  # speech that started before the hush
    monkeypatch.setattr(s, "_tts", lambda t: "/tmp/x.wav")
    s.speak("One. Two.", gen)
    assert sent == []


def test_leave_while_joining_never_joins(monkeypatch):
    s = voice._Session("b1", "", "local", {})  # noqa: SLF001
    monkeypatch.setattr(voice.bots, "get_token", lambda bid: "t")
    monkeypatch.setattr(voice, "ensure_env", lambda engine, say: (s.stop(), "py")[1])  # Leave pressed mid-install
    s.start()
    assert s.closed and s.proc is None
