"""Conservative Git synchronization with three-way local save reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import subprocess
import uuid

from .config import Paths, ThGitError, atomic_bytes, read_json, write_json
from .games import GAME_IDS, allowed, files, hashes


class Git:
    def __init__(self, repo: Path):
        self.repo = repo

    def run(self, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
        try:
            result = subprocess.run(["git", "-C", str(self.repo), *args],
                                    capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", env=env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ThGitError("Git timed out; local data is retained. Check connectivity/authentication.") from exc
        if check and result.returncode:
            raise ThGitError(f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def validate(self, ref: str | None = None) -> None:
        if ref:
            entries = self.run("ls-tree", "-rz", ref).stdout
            records = [entry.split("\t", 1) for entry in entries.split("\0") if entry]
        else:
            entries = self.run("ls-files", "--stage", "-z").stdout
            records = [entry.split("\t", 1) for entry in entries.split("\0") if entry]
        seen = set()
        for metadata, name in records:
            parts = metadata.split()
            if parts[0] != "100644" and parts[0] != "100755":
                raise ThGitError(f"Unsupported repository entry: {name}")
            if not ref and parts[2] != "0":
                raise ThGitError("Resolve the existing Git merge before synchronizing.")
            path = name.split("/", 1)
            valid = name == ".gitattributes" or (len(path) == 2 and path[0] in GAME_IDS and allowed(path[1]))
            if not valid or name.casefold() in seen:
                raise ThGitError(f"Unexpected/non-portable file in save repository: {name}")
            seen.add(name.casefold())
            if name == ".gitattributes":
                content = self.run("show", f"{ref or ''}:.gitattributes").stdout
                if content != "* binary\n":
                    raise ThGitError("Save repository .gitattributes must contain only '* binary'.")

    def commit(self) -> None:
        if self.run("diff", "--cached", "--quiet", check=False).returncode:
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.run("commit", "-m", f"AutoSave: {stamp}")


def initialize(paths: Paths, remote: str | None, branch: str | None) -> None:
    if paths.config.exists() or paths.repo.exists():
        raise ThGitError("Already initialized, or saves directory exists. Use a new --home or inspect it first.")
    paths.data.mkdir(parents=True, exist_ok=True)
    if branch:
        Git(paths.data).run("check-ref-format", "--branch", branch)
    if remote:
        args = ["clone", "--no-checkout"]
        if branch:
            args += ["--branch", branch]
        Git(paths.data).run(*args, "--", remote, str(paths.repo))
    else:
        paths.repo.mkdir()
        Git(paths.repo).run("init", "-b", branch or "main")
    git = Git(paths.repo)
    git.run("config", "core.autocrlf", "false")
    # Ignore repository-supplied hooks and filters; this repository only stores bytes.
    hooks = paths.state / "empty-hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    git.run("config", "core.hooksPath", str(hooks.resolve()))
    if git.run("rev-parse", "--verify", "HEAD", check=False).returncode == 0:
        git.validate("HEAD")
        git.run("reset", "--hard", "HEAD")  # Only in this newly created, empty checkout.
    detected = git.run("symbolic-ref", "--short", "HEAD").stdout.strip()
    if not detected:
        raise ThGitError("The remote HEAD does not name a branch. Specify --branch.")
    atomic_bytes(paths.repo / ".gitattributes", b"* binary\n")
    git.run("add", "--", ".gitattributes")
    paths.save({"version": 1, "branch": detected, "games": {}})


class Sync:
    def __init__(self, paths: Paths, config: dict):
        self.paths, self.config = paths, config
        self.git = Git(paths.repo)
        self.manifest = paths.state / "baseline.json"
        self.captured: dict[str, dict[str, str]] = {}

    def check(self) -> None:
        if self.paths.session.exists():
            raise ThGitError("Previous game session did not finish. Close the game, then run 'recover --confirm-stopped'.")
        self.git.validate()
        branch = self.git.run("symbolic-ref", "--short", "HEAD").stdout.strip()
        if branch != self.config["branch"]:
            raise ThGitError("Save repository branch differs from config.toml.")
        for game_id, game in self.config.get("games", {}).items():
            if game_id not in GAME_IDS:
                raise ThGitError(f"Unsupported game: {game_id}")
            folder = Path(game["path"])
            if not folder.is_dir():
                raise ThGitError(f"Game directory missing; refusing to infer deleted saves: {folder}")
            if folder == self.paths.repo or self.paths.repo in folder.parents or folder in self.paths.repo.parents:
                raise ThGitError("Game directories and the save repository must be separate.")

    def backup(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        target = self.paths.state / "backups" / stamp
        target.mkdir(parents=True)
        for game_id, game in self.config.get("games", {}).items():
            for label, root in (("game", Path(game["path"])), ("repository", self.paths.repo / game_id)):
                for rel, source in files(root, game.get("sync_config", False)).items():
                    dest = target / label / game_id / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
        write_json(target / "baseline.json", read_json(self.manifest))
        return target

    def capture(self) -> None:
        """Import only changes since deployment; do not overwrite newer remote files."""
        baseline = read_json(self.manifest)
        changes = []
        conflicts = []
        for game_id, game in self.config.get("games", {}).items():
            folder = Path(game["path"])
            use_cfg = game.get("sync_config", False)
            current = hashes(folder, use_cfg)
            self.captured[game_id] = current
            saved = hashes(self.paths.repo / game_id, use_cfg)
            previous = {name: value for name, value in baseline.get(game_id, {}).items() if allowed(name, use_cfg)}
            for name in current.keys() | previous.keys():
                local, old, repo = current.get(name), previous.get(name), saved.get(name)
                if local == old:
                    continue
                if repo != old and repo != local:
                    conflicts.append(f"{game_id}/{name}")
                else:
                    changes.append((game_id, name, folder / name if local is not None else None))
        if conflicts:
            raise ThGitError("Local/repository saves both changed: " + ", ".join(conflicts)
                             + ". Both copies are retained; use 'resolve-local GAME --take game|repository'.")
        # Back up before any copy/delete, including first import and interrupted sessions.
        self.backup()
        for game_id, name, source in changes:
            destination = self.paths.repo / game_id / name
            if destination.is_symlink():
                raise ThGitError(f"Refusing to overwrite symlink: {destination}")
            if source is None:
                destination.unlink(missing_ok=True)
            else:
                atomic_bytes(destination, source.read_bytes())
        self.stage()
        self.git.commit()

    def stage(self) -> None:
        self.git.run("add", "--", ".gitattributes")
        for game_id, game in self.config.get("games", {}).items():
            root = self.paths.repo / game_id
            tracked = self.git.run("ls-files", "-z", "--", game_id).stdout.split("\0")
            names = {f"{game_id}/{name}" for name in files(root, game.get("sync_config", False))}
            names |= {name for name in tracked if name and allowed(name[len(game_id) + 1:], game.get("sync_config", False))}
            for name in sorted(names):
                self.git.run("--literal-pathspecs", "add", "-A", "--", name)
        self.git.validate()

    def fetch_merge(self) -> None:
        if not self.git.run("remote").stdout.strip():
            return
        self.git.run("fetch", "origin")
        target = f"refs/remotes/origin/{self.config['branch']}"
        if self.git.run("rev-parse", "--verify", target, check=False).returncode:
            # An empty remote is valid; a deleted/misspelled branch on a populated remote is not.
            if self.git.run("ls-remote", "--heads", "origin").stdout.strip():
                raise ThGitError("Configured remote branch is missing; check config.toml.")
            return
        self.git.validate(target)
        if self.git.run("merge", "--no-edit", target, check=False).returncode:
            if self.git.run("rev-parse", "--verify", "MERGE_HEAD", check=False).returncode == 0:
                self.git.run("merge", "--abort")
            raise ThGitError("Remote histories could not be merged. Local commits and remote history are retained; "
                             "resolve the merge in the saves repository or explicitly use --offline.")
        self.git.validate()

    def deploy(self) -> None:
        baseline = read_json(self.manifest)
        # Abort before writing anything if a directly launched game changed files during fetch.
        for game_id, game in self.config.get("games", {}).items():
            if hashes(Path(game["path"]), game.get("sync_config", False)) != self.captured.get(game_id):
                raise ThGitError("Game saves changed during synchronization; close all games and retry.")
        # A backup of the game files already exists from capture().
        for game_id, game in self.config.get("games", {}).items():
            folder = Path(game["path"])
            use_cfg = game.get("sync_config", False)
            saved = files(self.paths.repo / game_id, use_cfg)
            current = files(folder, use_cfg)
            for name, source in saved.items():
                atomic_bytes(folder / name, source.read_bytes())
            for name in current.keys() - saved.keys():
                current[name].unlink()
            baseline[game_id] = hashes(folder, use_cfg)
        write_json(self.manifest, baseline)

    def push(self) -> None:
        if self.git.run("remote").stdout.strip():
            self.git.run("push", "-u", "origin", self.config["branch"])

    def synchronize(self, offline: bool = False) -> None:
        self.check()
        self.capture()
        if not offline:
            self.fetch_merge()
        self.deploy()
        if not offline:
            self.push()

    def resolve_local(self, game_id: str, take: str) -> None:
        self.check()
        if game_id not in self.config.get("games", {}):
            raise ThGitError(f"Game not registered: {game_id}")
        self.backup()
        game = self.config["games"][game_id]
        use_cfg = game.get("sync_config", False)
        folder, repo = Path(game["path"]), self.paths.repo / game_id
        source, destination = (folder, repo) if take == "game" else (repo, folder)
        wanted, existing = files(source, use_cfg), files(destination, use_cfg)
        for name, path in wanted.items():
            atomic_bytes(destination / name, path.read_bytes())
        for name in existing.keys() - wanted.keys():
            existing[name].unlink()
        self.stage()
        self.git.commit()
        baseline = read_json(self.manifest)
        baseline[game_id] = hashes(folder, use_cfg)
        write_json(self.manifest, baseline)
