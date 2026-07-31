# Discord

Discord bot chat, !ducky commands, and agent server-admin tools in UEFN Ducky.

Desktop plugin for [UEFN-Ducky](https://github.com/UEFN-Ducky/UEFN-Ducky) (`discord`).
Owns its full backend (`bots` / `client` / `poller` / `presence` / `commands` / MCP tools)
and Phase-2 HTML UI (`ui/settings.html`, `ui/chat.html`).

Install or update from **Settings → Store** in the app — do not install from a zip by hand.

## Build

```bash
py scripts/build_zip.py
```

Writes `deploy/discord-1.1.0.ducky-plugin.zip` (scripts/ and deploy/ are not packed).

## Secrets

Never commit tokens or keys. The app stores `discord`, `discord_guild`, `discord_name`, `discord_allowed_ids`, `discord_channel` (and per-bot `discord:<id>`) locally (DPAPI), not in this package.
