"""Explicit save allowlists; never copy or stage game binaries."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import hashlib

from .config import ThGitError

GAME_IDS = ("th06", "th07", "th08", "th09")


def allowed(relative: str, sync_config: bool = True) -> bool:
    path = PurePosixPath(relative)
    if path.is_absolute() or any(p in ("..", ".") for p in path.parts) or "\\" in relative:
        return False
    reserved = {"con", "prn", "aux", "nul"} | {f"{kind}{n}" for kind in ("com", "lpt") for n in range(1, 10)}
    if any(p.endswith((".", " ")) or p.split(".")[0].casefold() in reserved
           or any(ord(c) < 32 or c in '<>:"|?*' for c in p) for p in path.parts):
        return False
    return (relative == "score.dat"
            or (len(path.parts) == 2 and path.parts[0] == "replay" and path.suffix.lower() == ".rpy")
            or (sync_config and len(path.parts) == 1 and path.suffix.lower() == ".cfg"))


def files(root: Path, sync_config: bool = False) -> dict[str, Path]:
    if root.is_symlink():
        raise ThGitError(f"Symlink directory is not supported: {root}")
    if not root.exists():
        return {}
    if not root.is_dir():
        raise ThGitError(f"Not a directory: {root}")
    candidates = list(root.iterdir())
    replay = root / "replay"
    if replay.is_symlink():
        raise ThGitError(f"Symlink replay directory is not supported: {replay}")
    if replay.exists():
        if not replay.is_dir():
            raise ThGitError(f"Not a directory: {replay}")
        candidates += list(replay.iterdir())
    result = {}
    folded = set()
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if not allowed(rel, sync_config):
            continue
        if path.is_symlink() or not path.is_file():
            raise ThGitError(f"Save must be a regular file: {path}")
        if rel.casefold() in folded:
            raise ThGitError(f"Case-colliding save names are not portable: {path}")
        folded.add(rel.casefold())
        result[rel] = path
    return result


def hashes(root: Path, sync_config: bool = False) -> dict[str, str]:
    return {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in files(root, sync_config).items()}


def register(config: dict, game_id: str, folder: Path, exe: str | None,
             sync_config: bool = False) -> None:
    if game_id not in GAME_IDS:
        raise ThGitError(f"Supported games: {', '.join(GAME_IDS)}")
    if game_id in config.get("games", {}):
        raise ThGitError(f"{game_id} is already registered. Edit config.toml to change its path.")
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise ThGitError(f"Game directory not found: {folder}")
    executable = exe or ("vpatch.exe" if (folder / "vpatch.exe").is_file() else f"{game_id}.exe")
    if Path(executable).name != executable or "/" in executable or "\\" in executable:
        raise ThGitError("--exe must be a filename inside the game directory.")
    if not (folder / executable).is_file():
        raise ThGitError(f"Executable not found: {folder / executable}; use --exe NAME.exe.")
    if any(Path(game["path"]).resolve() == folder for game in config.get("games", {}).values()):
        raise ThGitError("A directory cannot be registered for multiple games.")
    files(folder, sync_config)
    config.setdefault("games", {})[game_id] = {
        "path": str(folder), "exe": executable, "sync_config": sync_config,
    }
