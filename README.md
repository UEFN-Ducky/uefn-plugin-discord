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

## Next release: ship compiled

This plugin still ships its Python source on the Store. Its next release has to ship compiled and signed, the way Ducky Account and Roguelike do:

1. Give `scripts/release.py` and `scripts/build_zip.py` the compiled build from `uefn-plugin-account` (`build_compiled_zip`, upload by ticket, `--plain` only as an escape hatch).
2. Bump `version` and set `min_app_version` to `1.2.357` or newer (the Store keeps older apps from seeing it).
3. Build only with the UEFN Ducky build engine (UEFN-Ducky `68f4abc` or newer), which compiles and links for baseline x86-64, never with Nuitka or zig run by hand. Before publishing, check the `.pyd` runs on every CPU: `objdump -d <file>.pyd | grep -cE '%(y|z)mm'` must print `0`. Account 1.0.50 and Roguelike 1.12.44 carried the build PC's AVX-512 and stopped Ducky opening on every CPU without it.
4. Publish, then check the download with the start-up license check (signature, id and version, compiled, team access), not only the signature.
5. A compiled build can't `importlib.reload` its own modules (Python raises SystemError), so reload only when running from source. Before publishing, install the source and compiled zips into a throwaway Ducky and check they register the same panel calls, tools and workflow nodes, and that those calls still work after the plugin reloads.

Remove this section once a compiled version is live.

## License

MIT. Copyright (c) 2026 Mindful Path Company, LLC. See [LICENSE](LICENSE).
