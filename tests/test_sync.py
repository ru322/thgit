"""Real local Git repositories exercise preservation, divergence and retries."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from thgit.cli import main
from thgit.config import Paths, ThGitError, read_json, write_json
from thgit.games import files, register
from thgit.sync import Git, Sync, initialize


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Do not depend on the developer's global Git identity/configuration.
        self.env = patch.dict(os.environ, {
            "GIT_AUTHOR_NAME": "ThGit test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "ThGit test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.paths, self.config, self.folder = self.machine("a")

    def machine(self, name, remote=None):
        paths = Paths.default(str(self.root / name))
        initialize(paths, str(remote) if remote else None, None)
        folder = self.root / f"ゲーム {name}"
        folder.mkdir()
        (folder / "th06.exe").write_bytes(b"not a real executable")
        config = paths.load()
        register(config, "th06", folder, None)
        paths.save(config)
        return paths, config, folder

    def sync(self, offline=True):
        Sync(self.paths, self.config).synchronize(offline)

    def remote(self):
        self.sync()
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
        git(self.paths.repo, "remote", "add", "origin", str(remote))
        self.sync(False)
        return remote

    def test_offline_commit_and_allowlist(self):
        (self.folder / "score.dat").write_bytes(b"score")
        (self.folder / "th06.dat").write_bytes(b"game archive")
        (self.folder / "th06.cfg").write_bytes(b"machine settings")
        (self.folder / "replay").mkdir()
        (self.folder / "replay" / "th6_01.rpy").write_bytes(b"replay")
        (self.folder / "replay" / "bad.exe").write_bytes(b"binary")
        self.sync()
        self.assertEqual(set(git(self.paths.repo, "ls-files").splitlines()),
                         {".gitattributes", "th06/score.dat", "th06/replay/th6_01.rpy"})
        self.assertEqual((self.folder / "th06.cfg").read_bytes(), b"machine settings")
        self.assertTrue(git(self.paths.repo, "rev-parse", "HEAD"))

    def test_pending_commit_is_pushed_even_without_new_changes(self):
        remote = self.remote()
        (self.folder / "score.dat").write_bytes(b"offline progress")
        self.sync()
        self.sync(False)
        self.assertEqual(git(self.paths.repo, "rev-parse", "HEAD"), git(remote, "rev-parse", "main"))

    def test_two_machine_round_trip_and_remote_deletion(self):
        (self.folder / "score.dat").write_bytes(b"one")
        remote = self.remote()
        other, config, folder = self.machine("b", remote)
        Sync(other, config).synchronize()
        self.assertEqual((folder / "score.dat").read_bytes(), b"one")
        (folder / "score.dat").write_bytes(b"two")
        Sync(other, config).synchronize()
        self.sync(False)
        self.assertEqual((self.folder / "score.dat").read_bytes(), b"two")
        (folder / "score.dat").unlink()
        Sync(other, config).synchronize()
        self.sync(False)
        self.assertFalse((self.folder / "score.dat").exists())

    def test_binary_divergence_preserves_both_histories_and_game(self):
        (self.folder / "score.dat").write_bytes(b"base")
        remote = self.remote()
        other, config, folder = self.machine("b", remote)
        Sync(other, config).synchronize()
        (self.folder / "score.dat").write_bytes(b"local progress")
        self.sync()
        local_head = git(self.paths.repo, "rev-parse", "HEAD")
        (folder / "score.dat").write_bytes(b"remote progress")
        Sync(other, config).synchronize()
        with self.assertRaisesRegex(ThGitError, "could not be merged"):
            self.sync(False)
        self.assertEqual(git(self.paths.repo, "rev-parse", "HEAD"), local_head)
        self.assertEqual((self.folder / "score.dat").read_bytes(), b"local progress")
        self.assertEqual(git(self.paths.repo, "show", "origin/main:th06/score.dat"), "remote progress")
        self.assertFalse((self.paths.repo / ".git/MERGE_HEAD").exists())
        self.sync()  # Explicit offline play is still possible after merge failure.

    def test_non_overlapping_changes_merge(self):
        remote = self.remote()
        other, config, folder = self.machine("b", remote)
        Sync(other, config).synchronize()
        (self.folder / "score.dat").write_bytes(b"local score")
        self.sync()
        (folder / "replay").mkdir()
        (folder / "replay/a.rpy").write_bytes(b"remote replay")
        Sync(other, config).synchronize()
        self.sync(False)
        self.assertEqual((self.folder / "score.dat").read_bytes(), b"local score")
        self.assertEqual((self.folder / "replay/a.rpy").read_bytes(), b"remote replay")

    def test_first_import_conflict_and_explicit_resolution(self):
        (self.folder / "score.dat").write_bytes(b"remote")
        remote = self.remote()
        other, config, folder = self.machine("b", remote)
        (folder / "score.dat").write_bytes(b"existing local")
        sync = Sync(other, config)
        with self.assertRaisesRegex(ThGitError, "both changed"):
            sync.synchronize(True)
        self.assertEqual((folder / "score.dat").read_bytes(), b"existing local")
        sync.resolve_local("th06", "repository")
        self.assertEqual((folder / "score.dat").read_bytes(), b"remote")
        backups = list((other.state / "backups").glob("*/game/th06/score.dat"))
        self.assertTrue(any(path.read_bytes() == b"existing local" for path in backups))

    def test_game_choice_preserves_local_deletion(self):
        (self.folder / "score.dat").write_bytes(b"base")
        self.sync()
        (self.folder / "score.dat").unlink()
        (self.paths.repo / "th06/score.dat").write_bytes(b"other")
        sync = Sync(self.paths, self.config)
        with self.assertRaises(ThGitError):
            sync.synchronize(True)
        sync.resolve_local("th06", "game")
        self.assertFalse((self.paths.repo / "th06/score.dat").exists())
        self.assertNotIn("th06/score.dat", git(self.paths.repo, "ls-files"))

    def test_missing_game_directory_does_not_delete_saves(self):
        (self.folder / "score.dat").write_bytes(b"preserve")
        self.sync()
        self.folder.rename(self.folder.with_name("moved"))
        with self.assertRaisesRegex(ThGitError, "directory missing"):
            self.sync()
        self.assertEqual((self.paths.repo / "th06/score.dat").read_bytes(), b"preserve")

    def test_session_marker_blocks_sync_and_recovery_preserves_changes(self):
        (self.folder / "score.dat").write_bytes(b"after crash")
        write_json(self.paths.session, {"game": "th06"})
        with self.assertRaisesRegex(ThGitError, "session"):
            self.sync()
        self.assertEqual(main(["--home", str(self.root / "a"), "recover", "--confirm-stopped"]), 0)
        self.sync()
        self.assertEqual(git(self.paths.repo, "show", "HEAD:th06/score.dat"), "after crash")

    def test_changes_during_fetch_are_not_overwritten(self):
        (self.folder / "score.dat").write_bytes(b"start")
        sync = Sync(self.paths, self.config)
        sync.check()
        sync.capture()
        (self.folder / "score.dat").write_bytes(b"concurrent writer")
        with self.assertRaisesRegex(ThGitError, "during synchronization"):
            sync.deploy()
        self.assertEqual((self.folder / "score.dat").read_bytes(), b"concurrent writer")

    def test_fetch_failure_keeps_local_commit(self):
        (self.folder / "score.dat").write_bytes(b"offline")
        git(self.paths.repo, "remote", "add", "origin", str(self.root / "missing.git"))
        with self.assertRaises(ThGitError):
            self.sync(False)
        self.assertEqual(git(self.paths.repo, "show", "HEAD:th06/score.dat"), "offline")
        self.assertEqual((self.folder / "score.dat").read_bytes(), b"offline")

    def test_config_files_are_opt_in(self):
        self.config["games"]["th06"]["sync_config"] = True
        (self.folder / "th06.cfg").write_bytes(b"settings")
        self.sync()
        self.assertEqual(git(self.paths.repo, "show", "HEAD:th06/th06.cfg"), "settings")

    def test_remote_executable_is_rejected_before_deployment(self):
        remote = self.remote()
        other, config, folder = self.machine("b", remote)
        (other.repo / "bad.exe").write_bytes(b"not a save")
        git(other.repo, "add", "bad.exe")
        git(other.repo, "commit", "-m", "unexpected file")
        git(other.repo, "push", "origin", "main")
        head = git(self.paths.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ThGitError, "Unexpected"):
            self.sync(False)
        self.assertEqual(git(self.paths.repo, "rev-parse", "HEAD"), head)
        self.assertFalse((self.paths.repo / "bad.exe").exists())

    def test_new_clone_rejects_legacy_layout_before_checkout(self):
        remote = self.remote()
        (self.paths.repo / "old-game").mkdir()
        (self.paths.repo / "old-game/score.dat").write_bytes(b"legacy")
        git(self.paths.repo, "add", "old-game")
        git(self.paths.repo, "commit", "-m", "legacy layout")
        git(self.paths.repo, "push", "origin", "main")
        paths = Paths.default(str(self.root / "invalid"))
        with self.assertRaises(ThGitError):
            initialize(paths, str(remote), None)
        self.assertFalse((paths.repo / "old-game").exists())

    def test_remote_default_branch_is_detected(self):
        self.sync()
        git(self.paths.repo, "branch", "-m", "saves")
        remote = self.root / "custom.git"
        subprocess.run(["git", "clone", "--bare", str(self.paths.repo), str(remote)],
                       check=True, capture_output=True)
        other, config, folder = self.machine("custom", remote)
        self.assertEqual(config["branch"], "saves")

    def test_migration_keeps_legacy_repository_and_game_binaries(self):
        legacy = self.root / "legacy"
        game = legacy / "紅魔郷"
        game.mkdir(parents=True)
        (game / "th06.exe").write_bytes(b"exe")
        (game / "score.dat").write_bytes(b"legacy score")
        git(legacy, "init")
        # Use another empty new-format instance; migration never touches legacy .git.
        paths = Paths.default(str(self.root / "migration"))
        initialize(paths, None, None)
        self.assertEqual(main(["--home", str(self.root / "migration"), "migrate", str(legacy)]), 0)
        self.assertEqual((game / "th06.exe").read_bytes(), b"exe")
        self.assertEqual(git(paths.repo, "show", "HEAD:th06/score.dat"), "legacy score")
        self.assertEqual(git(legacy, "ls-files"), "")

    @unittest.skipIf(os.name == "nt", "Unprivileged Windows may not support symlinks")
    def test_symlink_save_is_rejected(self):
        outside = self.root / "private"
        outside.write_bytes(b"private")
        (self.folder / "score.dat").symlink_to(outside)
        with self.assertRaisesRegex(ThGitError, "regular file"):
            self.sync()
        self.assertEqual(outside.read_bytes(), b"private")

    def test_paths_with_unicode_quotes_and_spaces_round_trip(self):
        config = self.paths.load()
        self.assertEqual(config["games"]["th06"]["path"], str(self.folder.resolve()))
        self.assertEqual(config["games"]["th06"]["exe"], "th06.exe")


if __name__ == "__main__":
    unittest.main()
