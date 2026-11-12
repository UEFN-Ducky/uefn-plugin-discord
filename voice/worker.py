"""Discord voice worker — runs in its own venv (discord.py + DAVE), driven by the Discord plugin.

Why a separate process: Discord voice needs native packages (Opus, PyNaCl, davey for the
mandatory E2EE) that the app's Python can't load. The plugin starts this with
``python -I worker.py`` and the bot token in ``DISCORD_TOKEN``.

stdin (JSON lines from the plugin):
  {"cmd": "join", "guild_id": "...", "channel_id": "..."}       join that voice channel
  {"cmd": "join", "guild_id": "...", "user_id": "..."}          join where that user is
  {"cmd": "play", "path": "C:/.../reply.wav", "keep": false}     queue a file (deleted after unless keep)
  {"cmd": "stop"}                                               stop speaking, drop the queue
  {"cmd": "leave"}                                              leave voice
  {"cmd": "stt", "engine": "local"|"openai"}                    who transcribes
stdout (JSON lines to the plugin):
  {"ev": "ready"} | {"ev": "joined", "channel_id", "channel"} | {"ev": "left"}
  {"ev": "utterance", "user_id", "user", "wav", "text"?}       text only when engine=local
  {"ev": "error", "error"}
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import sys
import tempfile
import threading
import time
import wave

import discord
from discord.ext import voice_recv

_RATE, _CH, _SW = 48000, 2, 2
_BYTES_PER_S = _RATE * _CH * _SW
# Discord stops sending packets when you stop talking; 0.55 s feels like a real turn-take.
_SILENCE_S = float(os.environ.get("BOB_SILENCE_S", "0.55"))
_MIN_UTTER_S = 0.5
_MAX_UTTER_S = 30.0

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
_out_lock = threading.Lock()


def emit(**ev) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps(ev) + "\n")
        sys.stdout.flush()


def write_wav(pcm: bytes) -> str:
    fd, path = tempfile.mkstemp(prefix="bob_heard_", suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(_CH)
        w.setsampwidth(_SW)
        w.setframerate(_RATE)
        w.writeframes(pcm)
    return path


class Ears(voice_recv.AudioSink):
    """Buffers each speaker's PCM; the flusher turns a pause into one utterance."""

    def __init__(self, worker: "Worker") -> None:
        super().__init__()
        self.worker = worker
        self.lock = threading.Lock()
        self.bufs: dict[int, bytearray] = {}
        self.last: dict[int, float] = {}
        self.names: dict[int, str] = {}

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data) -> None:  # router thread
        uid = getattr(user, "id", None) or self.worker.only_human()
        if not uid or not data.pcm:
            return
        if self.worker.playing():
            self.worker.barge_in()  # you talk over BoB → he stops
        with self.lock:
            self.bufs.setdefault(uid, bytearray()).extend(data.pcm)
            self.last[uid] = time.monotonic()
            if user is not None:
                self.names[uid] = getattr(user, "display_name", None) or str(user)

    def cleanup(self) -> None:
        with self.lock:
            self.bufs.clear()

    def take_finished(self) -> list[tuple[int, str, bytes]]:
        now = time.monotonic()
        out = []
        with self.lock:
            for uid, buf in list(self.bufs.items()):
                done = now - self.last.get(uid, now) >= _SILENCE_S
                if done or len(buf) >= _MAX_UTTER_S * _BYTES_PER_S:
                    pcm = bytes(self.bufs.pop(uid))
                    if len(pcm) >= _MIN_UTTER_S * _BYTES_PER_S:
                        out.append((uid, self.names.get(uid, "someone"), pcm))
        return out


class Worker:
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        self.client = discord.Client(intents=intents)
        self.vc: voice_recv.VoiceRecvClient | None = None
        self.ears: Ears | None = None
        self.engine = "openai"
        self._whisper = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: collections.deque[tuple[str, bool]] = collections.deque()

        @self.client.event
        async def on_ready() -> None:
            emit(ev="ready", user=str(self.client.user))

    # ---- helpers the sink calls from its thread ----
    def only_human(self) -> int | None:
        """SPEAKING can be missing under DAVE: with one human in the call, it's them."""
        ch = self.vc.channel if self.vc else None
        me = self.client.user.id if self.client.user else 0
        ids = [uid for uid in (getattr(ch, "voice_states", {}) or {}) if uid != me]
        return ids[0] if len(ids) == 1 else None

    def playing(self) -> bool:
        return bool(self.vc and self.vc.is_playing())

    def barge_in(self) -> None:
        if self.vc and self.loop:
            self.loop.call_soon_threadsafe(self.stop_speaking)

    def stop_speaking(self) -> None:
        while self.queue:
            path, keep = self.queue.popleft()
            if not keep:
                _unlink(path)
        if self.vc:
            self.vc.stop()

    # ---- commands ----
    async def join(self, guild_id: str, channel_id: str = "", user_id: str = "") -> None:
        guild = self.client.get_guild(int(guild_id))
        if guild is None:
            raise RuntimeError(f"bot is not in server {guild_id}")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None and user_id:
            uid = int(user_id)
            channel = next((c for c in guild.voice_channels if uid in c.voice_states), None)
            if channel is None:
                channel = next((c for c in guild.stage_channels if uid in c.voice_states), None)
        if channel is None:
            raise RuntimeError("join a voice channel first (or give its channel id)")
        if self.vc and self.vc.is_connected():
            if self.vc.channel.id == channel.id:
                emit(ev="joined", channel_id=str(channel.id), channel=channel.name)
                return
            await self.vc.move_to(channel)
        else:
            # self_deaf=False or Discord never sends audio to the bot.
            self.vc = await channel.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False)
        await self._wait_dave()
        self.ears = Ears(self)
        self.vc.listen(self.ears, after=self._listen_ended)
        emit(ev="joined", channel_id=str(channel.id), channel=channel.name)

    async def _wait_dave(self) -> None:
        conn = getattr(self.vc, "_connection", None)
        for _ in range(50):  # no "DAVE ready" event; poll up to 5 s
            ds = getattr(conn, "dave_session", None)
            if ds is None or getattr(ds, "ready", True):
                return
            await asyncio.sleep(0.1)

    def _listen_ended(self, err) -> None:
        if err:
            emit(ev="error", error=f"listening stopped: {err}")
            # ponytail: relisten once per failure; a crash loop shows as repeated errors
            if self.vc and self.vc.is_connected() and self.ears and self.loop:
                self.loop.call_soon_threadsafe(lambda: self.vc.listen(self.ears, after=self._listen_ended))

    async def leave(self) -> None:
        if self.vc:
            await self.vc.disconnect(force=True)
        self.vc = None
        self.ears = None
        emit(ev="left")

    def play(self, path: str, keep: bool = False) -> None:
        if not (self.vc and self.vc.is_connected()):
            if not keep:
                _unlink(path)
            return
        self.queue.append((path, keep))
        if not self.vc.is_playing():
            self._next()

    def _next(self) -> None:
        if not (self.queue and self.vc and self.vc.is_connected()) or self.vc.is_playing():
            return
        import imageio_ffmpeg

        path, keep = self.queue.popleft()

        def after(_e) -> None:
            if not keep:
                _unlink(path)
            if self.loop:
                self.loop.call_soon_threadsafe(self._next)

        src = discord.FFmpegPCMAudio(path, executable=imageio_ffmpeg.get_ffmpeg_exe())
        self.vc.play(src, after=after)

    # ---- utterances ----
    async def flusher(self) -> None:
        while True:
            await asyncio.sleep(0.15)
            if not self.ears:
                continue
            for uid, name, pcm in self.ears.take_finished():
                path = write_wav(pcm)
                text = None
                if self.engine == "local":
                    text = await asyncio.to_thread(self._local_stt, path)
                emit(ev="utterance", user_id=str(uid), user=name, wav=path, text=text)

    def _local_stt(self, path: str) -> str:
        if self._whisper is None:
            from faster_whisper import WhisperModel

            self._whisper = WhisperModel(os.environ.get("BOB_WHISPER_MODEL", "base"), compute_type="int8")
        segments, _info = self._whisper.transcribe(path, vad_filter=True, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()

    async def handle(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        try:
            if cmd == "join":
                await self.join(str(msg.get("guild_id") or ""), str(msg.get("channel_id") or ""), str(msg.get("user_id") or ""))
            elif cmd == "play":
                self.play(str(msg.get("path") or ""), bool(msg.get("keep")))
            elif cmd == "stop":
                self.stop_speaking()
            elif cmd == "leave":
                await self.leave()
            elif cmd == "stt":
                self.engine = "local" if msg.get("engine") == "local" else "openai"
            elif cmd == "quit":
                await self.leave()
                await self.client.close()
        except Exception as e:
            emit(ev="error", error=f"{cmd}: {e}")

    async def main(self) -> None:
        self.loop = asyncio.get_running_loop()
        threading.Thread(target=self._read_stdin, daemon=True).start()
        asyncio.create_task(self.flusher())
        await self.client.start(os.environ["DISCORD_TOKEN"])

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            asyncio.run_coroutine_threadsafe(self.handle(msg), self.loop)
        # Plugin gone (app closed) → don't linger in the call.
        asyncio.run_coroutine_threadsafe(self.handle({"cmd": "quit"}), self.loop)


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


if __name__ == "__main__":
    if not os.environ.get("DISCORD_TOKEN"):
        sys.exit("DISCORD_TOKEN not set")
    asyncio.run(Worker().main())
