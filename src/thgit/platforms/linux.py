"""Use host Git/Python and Wine only for the Windows executable."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from ..config import ThGitError


def environment(prefix: Path) -> dict[str, str]:
    return dict(os.environ, WINEPREFIX=str(prefix.resolve()))


def run(folder: Path, executable: str, prefix: Path) -> int:
    if not shutil.which("wine") or not shutil.which("wineserver"):
        raise ThGitError("Wine is missing. Use the Nix package or install Wine with 32-bit application support.")
    env = environment(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    if not (prefix / "system.reg").exists():
        subprocess.run(["wineboot", "-u"], env=env, check=True)
        subprocess.run(["wineserver", "-w"], env=env, check=True)
    result = subprocess.run(["wine", str(folder / executable)], cwd=folder, env=env)
    # vpatch can exit before its child; wait for this game's entire prefix.
    subprocess.run(["wineserver", "-w"], env=env, check=True)
    return result.returncode
