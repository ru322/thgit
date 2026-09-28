import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from thgit.config import ThGitError
from thgit.locking import locked
from thgit.platforms import linux


class PlatformTests(unittest.TestCase):
    def test_wine_wait_uses_same_prefix_and_game_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "prefix"
            prefix.mkdir()
            (prefix / "system.reg").touch()
            folder = Path(tmp) / "game 日本語"
            with patch.object(linux.shutil, "which", return_value="wine"), \
                 patch.object(linux.subprocess, "run", return_value=Mock(returncode=0)) as run:
                self.assertEqual(linux.run(folder, "vpatch.exe", prefix), 0)
            self.assertEqual(run.call_args_list[0].args[0], ["wine", str(folder / "vpatch.exe")])
            self.assertEqual(run.call_args_list[0].kwargs["cwd"], folder)
            self.assertEqual(run.call_args_list[1].args[0], ["wineserver", "-w"])
            self.assertEqual(run.call_args_list[0].kwargs["env"]["WINEPREFIX"], str(prefix.resolve()))
            self.assertEqual(run.call_args_list[0].kwargs["env"], run.call_args_list[1].kwargs["env"])

    def test_lock_excludes_another_process_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = ("from pathlib import Path; from thgit.locking import locked; "
                    f"lock=locked(Path({tmp!r})); lock.__enter__()")
            with locked(Path(tmp)):
                result = subprocess.run([sys.executable, "-c", code], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Another thgit", result.stderr)
            result = subprocess.run([sys.executable, "-c", code], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Real Windows Job Object integration test")
    def test_windows_waits_for_child_after_parent_exits(self):
        from thgit.platforms.windows import run
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "child-finished"
            child = f"import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).write_text('done')"
            parent = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child!r}])"
            executable = Path(sys.executable)
            self.assertEqual(run(executable.parent, executable.name, arguments=("-c", parent)), 0)
            self.assertEqual(marker.read_text(), "done")


if __name__ == "__main__":
    unittest.main()
