# Discord

Discord bot chat, !ducky commands, and agent server-admin tools in UEFN Ducky

Desktop plugin for [UEFN-Ducky](https://github.com/UEFN-Ducky/UEFN-Ducky) (`discord`).
Install or update from **Settings → Store** in the app — do not install from a zip by hand.

## Build

```bash
py scripts/build_zip.py
```

Writes `deploy/discord-1.0.15.ducky-plugin.zip` (scripts/ and deploy/ are not packed).

## Secrets

Never commit tokens or keys. The app stores `discord`, `discord_guild`, `discord_name`, `discord_allowed_ids`, `discord_channel` locally (DPAPI), not in this package.
