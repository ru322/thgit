"""Native Win32 execution: a Job Object tracks vpatch and its descendants."""

from __future__ import annotations

from pathlib import Path
import subprocess
import time
import uuid


def run(folder: Path, executable: str, prefix: Path | None = None, arguments: tuple[str, ...] = ()) -> int:
    import win32api
    import win32con
    import win32event
    import win32job
    import win32process

    job = win32job.CreateJobObject(None, "thgit-" + uuid.uuid4().hex)
    process = thread = None
    try:
        process, thread, _, _ = win32process.CreateProcess(
            str(folder / executable), subprocess.list2cmdline([str(folder / executable), *arguments]),
            None, None, False, win32con.CREATE_SUSPENDED, None, str(folder),
            win32process.STARTUPINFO(),
        )
        try:
            win32job.AssignProcessToJobObject(job, process)
            win32process.ResumeThread(thread)
        except BaseException:
            # No child has run yet; do not leave a suspended process behind.
            win32process.TerminateProcess(process, 1)
            raise
        while True:
            try:
                info = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)
                if info["ActiveProcesses"] == 0:
                    break
                time.sleep(0.1)
            except KeyboardInterrupt:
                print("Close the game to finish safely; waiting for all game processes...")
        win32event.WaitForSingleObject(process, win32event.INFINITE)
        return win32process.GetExitCodeProcess(process)
    finally:
        # Deliberately no KILL_ON_JOB_CLOSE: an interrupted launcher must not kill a save write.
        for handle in (thread, process, job):
            if handle is not None:
                win32api.CloseHandle(handle)
