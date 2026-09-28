"""A durable session marker prevents deployment after an interrupted launcher."""

from pathlib import Path
import os
import logging
import sys

from .config import Paths, ThGitError, write_json
from .sync import Sync


def run_game(paths: Paths, config: dict, game_id: str, offline: bool) -> int:
    game = config.get("games", {}).get(game_id)
    if game is None:
        raise ThGitError(f"Game not registered: {game_id}")
    folder = Path(game["path"])
    executable = game["exe"]
    if Path(executable).name != executable or "/" in executable or "\\" in executable:
        raise ThGitError("Configured executable must be a filename in the game directory.")
    if not (folder / executable).is_file():
        raise ThGitError(f"Executable not found: {folder / executable}")
    if sys.platform == "win32":
        from .platforms.windows import run
    elif sys.platform == "linux":
        from .platforms.linux import run
    else:
        raise ThGitError("Supported platforms: Linux and Windows.")
    sync = Sync(paths, config)
    print("Saving and synchronizing before launch...")
    sync.synchronize(offline)
    logging.info("Starting %s", game_id)
    print(f"Starting {game_id}; waiting for the game and its child processes to exit.")
    write_json(paths.session, {"game": game_id, "pid": os.getpid()})
    # On exceptions or a killed launcher keep the marker; do not assume the game exited.
    result = run(folder, executable, paths.data / "prefixes" / game_id)
    paths.session.unlink()
    logging.info("%s exited with code %s", game_id, result)
    print("Game exited. Saving and synchronizing...")
    sync.synchronize(offline)
    return result
