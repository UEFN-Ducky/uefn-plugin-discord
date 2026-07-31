#!/usr/bin/env python3
"""Copy this package into ducky_app/frontend/uefn_plugins/discord for EXE seeding."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]  # UEFN-Ducky/
SEED = REPO / "ducky_app" / "frontend" / "uefn_plugins" / "discord"
SKIP = {".git", "scripts", "deploy", ".gitignore", "README.md", "__pycache__"}


def main() -> None:
    if not (ROOT / "plugin.json").is_file():
        raise SystemExit(f"missing plugin.json in {ROOT}")
    if SEED.exists():
        shutil.rmtree(SEED)
    SEED.mkdir(parents=True)
    for path in ROOT.iterdir():
        if path.name in SKIP or path.name.startswith("."):
            continue
        dest = SEED / path.name
        if path.is_dir():
            shutil.copytree(path, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(path, dest)
    # Mark as bundled for seed source field.
    import json

    manifest = json.loads((SEED / "plugin.json").read_text(encoding="utf-8"))
    manifest["source"] = "bundled"
    (SEED / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"synced {ROOT.name} -> {SEED}")


if __name__ == "__main__":
    main()
