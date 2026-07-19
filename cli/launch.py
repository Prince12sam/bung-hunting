"""One-shot startup: Docker check -> browser image -> Postgres/compose
services -> ffuf image -> Agent Core.

Exists because getting Scorpion running has always meant several manual
steps done in the right order (is Docker even up? is Postgres healthy? is
the locally-built ffuf image there? is the Agent Core started?) — this
session alone repeated that sequence by hand more times than is
reasonable. `launch()` does all of it, idempotently: each step is safe to
run again if it's already done.
"""

import subprocess
import time
from pathlib import Path

import httpx

from api.config import settings
from cli import server as server_lifecycle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCKER_DIR = PROJECT_ROOT / "docker"
FFUF_DOCKERFILE_DIR = DOCKER_DIR / "tools" / "ffuf"
BROWSER_DOCKERFILE_DIR = DOCKER_DIR / "tools" / "browser"

Step = tuple[bool, str]


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _postgres_healthy() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format={{.State.Health.Status}}", "es_postgres"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "healthy"


def _ensure_postgres() -> Step:
    if _postgres_healthy():
        return True, "Postgres already healthy."

    if not (DOCKER_DIR / ".env").exists():
        return False, (
            "docker/.env is missing — one-time setup step: "
            "cp docker/.env.example docker/.env, set a real password, then re-run."
        )

    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=DOCKER_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return False, f"docker compose up failed: {result.stderr.strip()[-500:]}"

    for _ in range(30):
        if _postgres_healthy():
            return True, "Postgres started and healthy."
        time.sleep(2)
    return False, "Postgres started but did not report healthy in time — check `docker compose logs`."


def _msf_rpc_ready() -> bool:
    from api.msf_client import MsfRpcClient, MsfRpcError

    try:
        MsfRpcClient().login()
        return True
    except MsfRpcError:
        return False


def _ensure_msf_services() -> Step:
    """Best-effort, never blocks the rest of launch(): docker compose up -d
    (in _ensure_postgres above) already started msf_postgres/msf_rpc
    alongside es_postgres, since they're all in the same compose file —
    this just waits for msfrpcd to actually finish loading. It's a heavy
    Rails app, genuinely slower than Postgres to become ready. If it's
    still not up by the time this returns, that's reported here but always
    as ok=True — a scan's msf-http-version stage degrades to a skipped/
    failed warning on its own if msfrpcd isn't reachable yet, the same way
    any other tool failure is handled, so this was never a reason to block
    the Agent Core from starting.
    """
    if _msf_rpc_ready():
        return True, "Metasploit RPC (msfrpcd) already healthy."

    for _ in range(30):
        if _msf_rpc_ready():
            return True, "Metasploit RPC (msfrpcd) started and healthy."
        time.sleep(2)
    return True, (
        "Metasploit RPC (msfrpcd) not ready yet — it's a heavy Rails app, can take a "
        "minute+ on first start. scan's msf-http-version stage will report skipped "
        "until it is; check `docker compose logs msf_rpc` if it never comes up."
    )


def _ffuf_image_exists() -> bool:
    result = subprocess.run(["docker", "image", "inspect", settings.ffuf_docker_image], capture_output=True)
    return result.returncode == 0


def _ensure_ffuf_image() -> Step:
    if _ffuf_image_exists():
        return True, f"{settings.ffuf_docker_image} already built."

    result = subprocess.run(
        ["docker", "build", "-t", settings.ffuf_docker_image, str(FFUF_DOCKERFILE_DIR)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        return False, f"ffuf image build failed: {result.stderr.strip()[-500:]}"
    return True, f"Built {settings.ffuf_docker_image}."


def _browser_image_exists() -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", settings.browser_sandbox_docker_image], capture_output=True
    )
    return result.returncode == 0


def _ensure_browser_image() -> Step:
    if _browser_image_exists():
        return True, f"{settings.browser_sandbox_docker_image} already built."

    result = subprocess.run(
        ["docker", "build", "-t", settings.browser_sandbox_docker_image, str(BROWSER_DOCKERFILE_DIR)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        return False, f"browser sandbox image build failed: {result.stderr.strip()[-500:]}"
    return True, f"Built {settings.browser_sandbox_docker_image}."


def _browser_sandbox_ready() -> bool:
    url = f"http://{settings.browser_sandbox_host}:{settings.browser_cdp_port}/json/version"
    try:
        return httpx.get(url, timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def _ensure_browser_sandbox() -> Step:
    """Best-effort, same non-blocking shape as _ensure_msf_services: docker
    compose up -d (in _ensure_postgres above) already started
    browser_sandbox alongside everything else in the compose file — this
    just waits for Chromium to actually finish starting inside it. A scan's
    adaptive-loop browser actions degrade to a skipped/failed warning on
    their own if the sandbox isn't reachable yet, same as any other tool
    outage, so this was never a reason to block the Agent Core."""
    if _browser_sandbox_ready():
        return True, "Browser sandbox already healthy."

    for _ in range(15):
        if _browser_sandbox_ready():
            return True, "Browser sandbox started and healthy."
        time.sleep(2)
    return True, (
        "Browser sandbox not ready yet — check `docker compose logs browser_sandbox` if it "
        "never comes up. Adaptive-loop browser actions will report skipped until it is."
    )


def launch() -> list[Step]:
    """Runs the full startup sequence, stopping at the first failed step."""
    steps: list[Step] = []

    if not _docker_available():
        steps.append(
            (
                False,
                "Docker isn't running or isn't reachable. Start Docker Desktop "
                "(Windows/Mac) or the docker daemon (Linux), then try again.",
            )
        )
        return steps
    steps.append((True, "Docker is running."))

    # browser_sandbox is a docker-compose service (unlike ffuf, a one-shot
    # `docker run` tool never referenced in docker-compose.yml) — its image
    # must exist *before* _ensure_postgres()'s `docker compose up -d`
    # brings up the whole compose file, or that call fails trying to start
    # a container from an image that doesn't exist yet.
    ok, msg = _ensure_browser_image()
    steps.append((ok, msg))
    if not ok:
        return steps

    ok, msg = _ensure_postgres()
    steps.append((ok, msg))
    if not ok:
        return steps

    ok, msg = _ensure_ffuf_image()
    steps.append((ok, msg))
    if not ok:
        return steps

    steps.append(_ensure_msf_services())
    steps.append(_ensure_browser_sandbox())

    ok, msg = server_lifecycle.start()
    steps.append((ok, msg))
    return steps
