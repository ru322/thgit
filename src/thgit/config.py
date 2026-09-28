"""Machine-local configuration and durable, atomic state files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tomllib
from dataclasses import dataclass


class ThGitError(Exception):
    """An actionable user-facing error."""


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".thgit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@dataclass(frozen=True)
class Paths:
    config: Path
    data: Path
    state: Path

    @classmethod
    def default(cls, home: str | None = None) -> Paths:
        if home:
            root = Path(home).expanduser().resolve()
            return cls(root / "config.toml", root / "data", root / "state")
        if os.name == "nt":
            root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "thgit"
            return cls(root / "config.toml", root / "data", root / "state")
        def xdg(key: str, fallback: str) -> Path:
            return Path(os.environ.get(key, str(Path.home() / fallback))) / "thgit"
        return cls(xdg("XDG_CONFIG_HOME", ".config") / "config.toml",
                   xdg("XDG_DATA_HOME", ".local/share"),
                   xdg("XDG_STATE_HOME", ".local/state"))

    @property
    def repo(self) -> Path:
        return self.data / "saves"

    @property
    def session(self) -> Path:
        return self.state / "session.json"

    def load(self) -> dict:
        if not self.config.exists():
            raise ThGitError("Run 'thgit init' first.")
        with self.config.open("rb") as stream:
            config = tomllib.load(stream)
        if config.get("version") != 1:
            raise ThGitError("Unsupported configuration version.")
        return config

    def save(self, config: dict) -> None:
        # JSON strings are a subset of TOML basic strings for these path values.
        def quote(value: str) -> str:
            return json.dumps(value, ensure_ascii=False)
        lines = ["version = 1", f"branch = {quote(config['branch'])}", ""]
        for game_id, game in sorted(config.get("games", {}).items()):
            lines += [f"[games.{game_id}]", f"path = {quote(game['path'])}",
                      f"exe = {quote(game['exe'])}",
                      f"sync_config = {str(game.get('sync_config', False)).lower()}", ""]
        atomic_bytes(self.config, "\n".join(lines).encode())
