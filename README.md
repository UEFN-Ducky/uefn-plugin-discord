# Discord

Discord bot chat, !ducky commands, and agent server-admin tools in UEFN Ducky.

Desktop plugin for [UEFN-Ducky](https://github.com/UEFN-Ducky/UEFN-Ducky) (`discord`).
Owns its full backend (`bots` / `client` / `poller` / `presence` / `commands` / MCP tools)
and Phase-2 HTML UI (`ui/settings.html`, `ui/chat.html`).

Install or update from **Settings → Store** in the app — do not install from a zip by hand.

For a full member list and Online/Offline status, enable **Server Members Intent** and
**Presence Intent** on the bot in the Discord Developer Portal (Bot → Privileged Gateway Intents).

**Job webhook:** Settings → Discord → “Notify when a ducky finishes”. Paste a Discord
Incoming Webhook URL (channel Integrations — not a bot token). When a chat in the
Ducky app ends a job (`agent_stopped` done/error/timeout), the plugin POSTs to that URL.

**Rich Presence:** Settings → Discord → “Rich Presence”. Shows “Playing Ducky” on your own
Discord profile while Ducky is open, with a session timer and a UEFN Ducky button. It talks to the
Discord desktop app over its local IPC pipe (`discord-ipc-N`), not the bot. The application,
image (Art Asset `ducky_1024`) and button are fixed in `backend/rich_presence.py`; users only switch
it on and pick what shows: whether UEFN is open and how many duckies are working. It never shows
project names or chat titles. On by default.

**Workflows:** the bot's jobs are workflows (Workflows tab). The **Discord message** trigger picks
the bot, the channel, @mentions only, and **Only these roles** — a role list for that one workflow,
separate from the agent allow list, so a role can start it without being able to talk to your agents.
**React to message** adds or swaps the bot's emoji (👀 while working, ✅ when done) and
**Send Discord message** replies with an Agent's text (split for Discord, never pings @everyone).
The **Discord PR review** template reviews a `github.com/UEFN-Ducky` pull request link in a sandbox
and merges only after the owner presses Allow (`gh pr merge --match-head-commit`).

**Voice, screen and invite** (`!bob` = your bot's prefix; only people on the bot's allow list can run these):

- `!bob join [openai|local] [ducky]` — the bot joins the voice channel you're in and talks with everyone.
  `openai` uses Ducky's OpenAI transcription + OpenAI speech (Settings → LLMs key); `local` uses
  faster-whisper and the Windows voice (free). The pick is remembered. A ducky with its own plugin voice
  (e.g. ElevenLabs) speaks in that voice. Only allow-listed speakers reach the agent and its tools;
  everyone else gets chat-only answers from a separate chat. First join sets up a venv under
  `%LOCALAPPDATA%\UEFN-Ducky\discord_voice` (needs Python 3.11+, 1-3 min).
- Or use Discord's **Invite to Voice** on the bot like on a person: an allow-listed sender's voice
  invite (DM'd to the bot) makes it join that channel. Anyone else's invite is ignored.
- **Talker + thinker:** every sentence goes to Ducky's live voice lane first (the fast voice
  model, Settings → LLMs → Voice), which answers at once. Real work is handed to the ducky's agent
  in the background; BoB keeps talking meanwhile and speaks a short summary when it's done.
- **Wake word:** in a call BoB answers only when called — "hey bob, …" — then keeps listening to
  that speaker for 20 s. `!bob wake <word>` changes it (comma-separate several), `!bob wake off`
  answers everything.
- `!bob leave` — hang up. `!bob show` (or say "show me the screen") — posts a screenshot.
- `!bob invite` — link that adds the bot to another server you manage.

Bots can't Go Live or share video on Discord, so "show me" is a screenshot.

This plugin is a **real Discord bot** (Gateway `MESSAGE_CREATE`) — not a REST poller.
**Show offline** disconnects the gateway (bot appears Offline; no `!commands` until Online again).
Enable **Message Content Intent** in the Dev Portal if gateway content is empty (we also hydrate via REST).

## Build

```bash
py scripts/build_zip.py
```

Writes `deploy/discord-<version>.ducky-plugin.zip` (scripts/ and deploy/ are not packed).

## Secrets

Never commit tokens or keys. The app stores `discord`, `discord_guild`, `discord_name`, `discord_allowed_ids`, `discord_channel` (and per-bot `discord:<id>`) locally (DPAPI), not in this package.

## License

MIT. Copyright (c) 2026 Mindful Path Company, LLC. See [LICENSE](LICENSE).
