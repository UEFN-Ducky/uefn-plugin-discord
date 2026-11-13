"""Worker checks. Run with the voice venv (needs discord.py + voice-recv + davey):
    <venv>\\Scripts\\python.exe -m pytest voice/test_worker.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker  # noqa: E402


class _Packet:
    def __init__(self, data=b"opus", silent=False):
        self.decrypted_data, self._silent = data, silent

    def is_silence(self):
        return self._silent


class _Dave:
    ready = True

    def __init__(self, owner):
        self.owner = owner

    def decrypt(self, uid, _media, data):
        if uid != self.owner:
            raise ValueError("wrong key")
        return data


def _vc(people, dave=None):
    return SimpleNamespace(
        user=SimpleNamespace(id=1),
        channel=SimpleNamespace(voice_states={1: None, **{p: None for p in people}}),
        _connection=SimpleNamespace(dave_session=dave),
    )


def test_only_person_in_call_is_the_speaker():
    assert worker.who_is_speaking(_vc([42]), _Packet()) == 42


def test_dave_key_picks_the_speaker_among_several():
    assert worker.who_is_speaking(_vc([42, 43, 44], _Dave(owner=43)), _Packet()) == 43


def test_unknown_when_nothing_to_go_on():
    assert worker.who_is_speaking(_vc([42, 43]), _Packet()) == 0  # no DAVE session
    assert worker.who_is_speaking(_vc([42, 43], _Dave(owner=43)), _Packet(silent=True)) == 0
    assert worker.who_is_speaking(_vc([]), _Packet()) == 0


def test_patch_maps_ssrc_before_decrypt(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_orig_process_packet", lambda self, p: calls.append(self._cached_id) or "data")
    vc = _vc([42])
    added = {}
    vc._get_id_from_ssrc = lambda ssrc: None
    vc._add_ssrc = lambda uid, ssrc: added.update({ssrc: uid})
    dec = SimpleNamespace(_cached_id=None, ssrc=777, vc=vc)
    assert worker._process_packet(dec, _Packet()) == "data"
    assert added == {777: 42} and calls == [42]  # library's decrypt now sees the speaker
