"""Agent Core process lifecycle: start/stop/status with a PID file.

Exists because manually backgrounding uvicorn (nohup/setsid/&/disown) is
exactly what caused a real incident: Ctrl+C in a terminal signals the
whole foreground process group, which silently killed a background
Agent Core that was never properly detached, and left a second, stale
instance answering requests with an old config with nothing to say so.
A PID file plus a real liveness check makes "is it running, and is it the
one I think it is" a fact, not something to reconstruct from `ps aux`.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from api.config import settings

PID_FILE = Path.home() / ".scorpion" / "agent-core.pid"
LOG_FILE = Path.home() / ".scorpion" / "agent-core.log"


def _pid_exists(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        return None
    if _pid_exists(pid):
        return pid
    PID_FILE.unlink(missing_ok=True)  # stale file from a process that's gone
    return None


def is_healthy() -> bool:
    try:
        response = httpx.get(f"http://{settings.host}:{settings.port}/healthz", timeout=3)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def start(foreground: bool = False) -> tuple[bool, str]:
    existing = read_pid()
    if existing is not None:
        return False, f"Already running (PID {existing})."

    # Found the hard way: checking only the PID file misses anything not
    # started through this module — an old, untracked instance (e.g. from
    # manually backgrounding uvicorn before `scorpion serve` existed) can
    # already be answering on the port. Spawning a second process on top of
    # it doesn't fail loudly; the health check below just ends up passing
    # because of the *other* process, making a broken new one look "started".
    if is_healthy():
        return False, (
            f"Something is already answering on {settings.host}:{settings.port}, "
            "but it's not tracked by a PID file (probably started outside "
            "`scorpion serve`/`launch`). Not starting a second instance — "
            "find and stop it manually first if it's not what you want."
        )

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", settings.host, "--port", str(settings.port)]

    if foreground:
        os.execvp(cmd[0], cmd)  # replaces this process entirely — used for `scorpion serve --foreground`

    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True  # detach from this terminal's session — the actual fix

    log_fh = open(LOG_FILE, "a")  # noqa: SIM115 - intentionally kept open for the child's lifetime
    process = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)
    PID_FILE.write_text(str(process.pid))

    for _ in range(settings.startup_health_check_retries):
        if is_healthy():
            return True, f"Started (PID {process.pid}). Logs: {LOG_FILE}"
        time.sleep(0.5)
    return False, f"Started (PID {process.pid}) but not responding yet — check {LOG_FILE}"


def stop() -> tuple[bool, str]:
    pid = read_pid()
    if pid is None:
        return False, "Not running."

    # On Windows, CTRL_BREAK_EVENT only works if the target shares a console —
    # it doesn't, since it's started with DETACHED_PROCESS. SIGTERM maps
    # directly to TerminateProcess() there instead, no console needed, so
    # use it on both platforms (POSIX just gets an actual graceful SIGTERM).
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, SystemError) as exc:
        return False, f"Could not signal PID {pid}: {exc}"

    for _ in range(20):
        if not _pid_exists(pid):
            PID_FILE.unlink(missing_ok=True)
            return True, f"Stopped (PID {pid})."
        time.sleep(0.5)

    if sys.platform != "win32":
        os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    return True, f"Force-stopped (PID {pid}) after it didn't exit gracefully."


def status() -> str:
    pid = read_pid()
    if pid is None:
        if is_healthy():
            return (
                f"Something is answering on {settings.host}:{settings.port}, but it's not "
                "tracked by a PID file (not started via `scorpion serve`/`launch`)."
            )
        return "Not running."
    healthy = is_healthy()
    return f"Running (PID {pid}), health check: {'ok' if healthy else 'NOT responding'}."
