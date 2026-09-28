"""Create native shortcuts without invoking PowerShell or a shell."""

from pathlib import Path
import os
import shutil
import subprocess
import sys

from .config import Paths, ThGitError, atomic_bytes


def desktop_quote(value: str) -> str:
    # Exec quoting, followed by Desktop Entry string escaping. % is a field-code escape.
    value = value.replace("%", "%%")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"'


def shortcut(paths: Paths, game_id: str, home: str | None) -> Path:
    command = shutil.which("thgit")
    if not command and Path(sys.argv[0]).name in ("thgit", "thgit.exe") and Path(sys.argv[0]).is_file():
        command = str(Path(sys.argv[0]).resolve())
    if not command:
        raise ThGitError("Install thgit first so the shortcut can use a stable executable path.")
    args = (["--home", str(Path(home).expanduser().resolve())] if home else []) + ["run", game_id]
    if sys.platform == "win32":
        from win32com.client import Dispatch
        shell = Dispatch("WScript.Shell")
        destination = Path(shell.SpecialFolders("Desktop")) / f"ThGit {game_id}.lnk"
        link = shell.CreateShortcut(str(destination))
        link.TargetPath = command
        link.Arguments = subprocess.list2cmdline(args)
        link.WorkingDirectory = str(paths.data)
        link.Description = f"ThGit {game_id}"
        link.Save()
    elif sys.platform == "linux":
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        destination = root / "applications" / f"thgit-{game_id}.desktop"
        entry = ("[Desktop Entry]\nType=Application\n"
                 f"Name=ThGit {game_id}\n"
                 f"Exec={' '.join(desktop_quote(arg) for arg in [command, *args])}\n"
                 "Terminal=true\nCategories=Game;\n")
        atomic_bytes(destination, entry.encode())
    else:
        raise ThGitError("Supported platforms: Linux and Windows.")
    return destination
