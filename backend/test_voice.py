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


def test_builtin_join_routes_to_voice(monkeypatch):
    seen = {}
    sent = []
    monkeypatch.setattr(voice, "join", lambda **kw: seen.update(kw) or {"ok": True, "engine": "local"})
    monkeypatch.setattr(commands, "_send", lambda cid, text, bid="default": sent.append(text))
    assert commands._run_builtin("join local verse", "c1", "default", "!bob", "u9")  # noqa: SLF001
    assert seen == {"bot_id": "default", "user_id": "u9", "text_channel_id": "c1", "engine": "local", "ducky": "verse"}
    assert "Joining" in sent[0]
    assert not commands._run_builtin("verse fix it", "c1", "default", "!bob", "u9")  # noqa: SLF001
