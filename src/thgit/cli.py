"""Command-line entry point; all mutations share one repository-wide lock."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config import Paths, ThGitError
from .games import GAME_IDS, register
from .locking import locked
from .sync import Git, Sync, initialize


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Touhou save sync and launcher (Linux / Windows)")
    root.add_argument("--home", help="Keep config, data and state under this directory")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a dedicated save repository")
    init.add_argument("--remote", help="New-format save repository URL (not the old game-root repo)")
    init.add_argument("--branch", help="Remote branch; default: remote HEAD, or main for local init")
    add = commands.add_parser("add", help="Register a game without changing its saves")
    add.add_argument("game", choices=GAME_IDS)
    add.add_argument("path", type=Path)
    add.add_argument("--exe", help="Executable filename; default: vpatch.exe, then GAME.exe")
    add.add_argument("--sync-config", action="store_true", help="Also synchronize *.cfg (machine-specific by default)")
    migrate = commands.add_parser("migrate", help="Import supported game folders from an old thgit installation")
    migrate.add_argument("path", type=Path)
    migrate.add_argument("--sync-config", action="store_true")
    for name in ("sync", "run"):
        command = commands.add_parser(name)
        if name == "run":
            command.add_argument("game", choices=GAME_IDS)
        command.add_argument("--offline", action="store_true", help="Commit locally without fetch/push")
    commands.add_parser("doctor", help="Report configuration, dependencies and unfinished sessions")
    desktop = commands.add_parser("shortcut", help="Create a native desktop/app-menu shortcut")
    desktop.add_argument("game", choices=GAME_IDS)
    recover = commands.add_parser("recover", help="Clear an interrupted session after closing all game processes")
    recover.add_argument("--confirm-stopped", action="store_true", required=True)
    resolve = commands.add_parser("resolve-local", help="Resolve a game/repository mismatch after backing up both copies")
    resolve.add_argument("game", choices=GAME_IDS)
    resolve.add_argument("--take", choices=("game", "repository"), required=True)
    return root


def doctor(paths: Paths) -> int:
    missing = []
    print(f"Platform: {sys.platform}\nConfig: {paths.config}\nSaves: {paths.repo}\nState: {paths.state}")
    for command in (["git", "wine", "wineboot", "wineserver"] if sys.platform == "linux" else ["git"]):
        location = shutil.which(command)
        print(f"{command}: {location or 'MISSING'}")
        if not location:
            missing.append(command)
    if sys.platform == "win32":
        try:
            import win32job  # noqa: F401
            import win32com.client  # noqa: F401
        except ImportError:
            missing.append("pywin32")
    if paths.session.exists():
        print("Unfinished game session: close the game, then recover --confirm-stopped")
        missing.append("session recovery")
    if paths.config.exists():
        config = paths.load()
        print(f"Branch: {config['branch']}; games: {', '.join(config.get('games', {})) or '(none)'}")
        if shutil.which("git"):
            git = Git(paths.repo)
            for key in ("user.name", "user.email"):
                if git.run("config", "--get", key, check=False).returncode:
                    print(f"Missing Git identity: {key}")
                    missing.append(key)
    if sys.platform == "linux":
        print("Graphics/audio and 32-bit game compatibility require a real launch test. "
              "On non-NixOS, host GPU driver integration may be needed.")
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            print("No graphical session detected (DISPLAY/WAYLAND_DISPLAY).")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    paths = Paths.default(args.home)
    try:
        paths.state.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=paths.state / "thgit.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
        if args.command == "doctor":
            return doctor(paths)
        with locked(paths.state):
            if args.command == "init":
                initialize(paths, args.remote, args.branch)
                print(f"Initialized {paths.repo}. Configure Git user.name/user.email before syncing.")
                return 0
            config = paths.load()
            if args.command == "recover":
                paths.session.unlink(missing_ok=True)
                print("Session marker cleared. Run sync (or sync --offline) to recover local saves.")
                return 0
            if paths.session.exists():
                raise ThGitError("Unfinished game session. Close the game, then recover --confirm-stopped.")
            if args.command == "add":
                register(config, args.game, args.path, args.exe, args.sync_config)
                paths.save(config)
                print(f"Registered {args.game}; run sync or run {args.game} to import saves.")
            elif args.command == "migrate":
                root = args.path.expanduser().resolve()
                if not root.is_dir():
                    raise ThGitError(f"Legacy directory not found: {root}")
                found = []
                for folder in sorted(root.iterdir()):
                    if not folder.is_dir() or folder.is_symlink() or folder.name.startswith((".", "_backup_")):
                        continue
                    for game_id in GAME_IDS:
                        if (folder / f"{game_id}.exe").is_file():
                            register(config, game_id, folder, None, args.sync_config)
                            found.append(game_id)
                if not found:
                    raise ThGitError("No th06–th09 game folders found. Use 'add GAME PATH --exe NAME.exe' if necessary.")
                paths.save(config)
                Sync(paths, config).synchronize(offline=True)
                print("Imported: " + ", ".join(found) + ". Old Git history is unchanged; stop using old PS shortcuts.")
            elif args.command == "sync":
                Sync(paths, config).synchronize(args.offline)
                print("Saved locally." if args.offline else "Synchronized.")
            elif args.command == "resolve-local":
                Sync(paths, config).resolve_local(args.game, args.take)
                print("Resolved local mismatch; both previous copies are in state/backups. Run sync next.")
            elif args.command == "run":
                from .runner import run_game
                return run_game(paths, config, args.game, args.offline)
            elif args.command == "shortcut":
                from .desktop import shortcut
                if args.game not in config.get("games", {}):
                    raise ThGitError(f"Game not registered: {args.game}")
                print(shortcut(paths, args.game, args.home))
        logging.info("Completed %s", args.command)
        return 0
    except (ThGitError, OSError, ValueError, subprocess.SubprocessError) as exc:
        logging.error("%s: %s", args.command, exc)
        print(f"thgit: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("thgit: interrupted; if a game was launched, close it before using recover --confirm-stopped.", file=sys.stderr)
        return 130
