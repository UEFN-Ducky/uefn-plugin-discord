"""Screenshot of the whole desktop (every monitor) as PNG bytes — Windows, no extra deps.

Discord bots can't Go Live, so BoB "shows you the computer" by posting a picture.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

_PS = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save($env:DUCKY_SHOT_PATH, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""


def capture_png() -> bytes:
    fd, path = tempfile.mkstemp(prefix="ducky_shot_", suffix=".png")
    os.close(fd)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
            env={**os.environ, "DUCKY_SHOT_PATH": path},
            check=True,
            timeout=20,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            raise RuntimeError("screenshot came back empty")
        return data
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def post_screenshot(channel_id: str, text: str = "", *, bot_id: str | None = None) -> dict:
    from . import client

    return client.send_file(channel_id, capture_png(), "screen.png", text=text, bot_id=bot_id)
