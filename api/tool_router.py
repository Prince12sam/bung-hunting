import json
import subprocess
from pathlib import Path

from api.config import settings


class ToolError(Exception):
    pass


def run_semgrep(path: Path) -> list[dict]:
    """Run semgrep against a local path, sandboxed in a container.

    Semgrep has no native Windows build, and containerizing it also matches
    docs/SECURITY_AND_AUTHORIZATION.md's sandboxing rule for every external
    tool the Tool Orchestrator runs.
    """
    abs_path = path.resolve()
    if not abs_path.exists():
        raise ToolError(f"path does not exist: {abs_path}")

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{abs_path}:/src:ro",
        settings.semgrep_docker_image,
        "semgrep", "scan", "--config=auto", "--json", "--quiet", "/src",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.semgrep_timeout_seconds)
    except FileNotFoundError as exc:
        raise ToolError("docker CLI not found — Docker Desktop must be installed and running") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"semgrep timed out after {settings.semgrep_timeout_seconds}s") from exc

    # semgrep exits 1 when it finds issues — that's not a tool failure.
    if result.returncode not in (0, 1):
        raise ToolError(f"semgrep failed (exit {result.returncode}): {result.stderr[-2000:]}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"could not parse semgrep output: {result.stderr[-2000:]}") from exc

    findings = []
    for r in data.get("results", []):
        extra = r.get("extra", {})
        findings.append(
            {
                "source_tool": "semgrep",
                "severity": extra.get("severity", "info").lower(),
                "title": r.get("check_id", "semgrep-finding"),
                "description": extra.get("message", ""),
                "file_path": r.get("path"),
                "line": (r.get("start") or {}).get("line"),
            }
        )
    return findings


def git_apply_patch(repo_path: Path, diff_text: str) -> None:
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=repo_path,
        input=diff_text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ToolError(f"git apply failed: {result.stderr.strip()}")


def run_tests(repo_path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["python", "-m", "pytest", "-q"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=settings.test_run_timeout_seconds,
    )
    return result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def git_commit(repo_path: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True, text=True)


def _run_docker(cmd: list[str], tool_name: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=settings.tool_timeout_seconds)
    except FileNotFoundError as exc:
        raise ToolError("docker CLI not found — Docker Desktop must be installed and running") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{tool_name} timed out after {settings.tool_timeout_seconds}s") from exc


def run_httpx(host: str) -> list[dict]:
    """HTTP fingerprinting via projectdiscovery/httpx, containerized."""
    cmd = [
        "docker", "run", "--rm",
        settings.httpx_docker_image,
        "-u", host, "-silent", "-json", "-status-code", "-title", "-tech-detect", "-server",
    ]
    result = _run_docker(cmd, "httpx")
    if result.returncode != 0 and not result.stdout.strip():
        raise ToolError(f"httpx failed (exit {result.returncode}): {result.stderr[-2000:]}")

    findings = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = r.get("status_code")
        title = r.get("title", "")
        tech = ", ".join(r.get("tech", []) or [])
        findings.append(
            {
                "source_tool": "httpx",
                "severity": "info",
                "title": f"HTTP {status} — {r.get('url', host)}",
                "description": f"title={title!r} server={r.get('webserver', '')!r} tech={tech}",
                "file_path": None,
                "line": None,
            }
        )
    return findings


def run_nmap(host: str, top_ports: int = 100, ports: str | None = None) -> list[dict]:
    """TCP port scan via instrumentisto/nmap, containerized.

    -Pn skips host discovery: ICMP from a container to the Docker Desktop
    host/VM network is frequently filtered, and skipping it is standard
    practice when the target is already known to be up. Pass `ports` (nmap
    -p syntax, e.g. "8080" or "1-1000") to scan a specific range instead of
    the top N most common ports.
    """
    port_arg = f"-p{ports}" if ports else f"--top-ports={top_ports}"
    cmd = [
        "docker", "run", "--rm",
        settings.nmap_docker_image,
        "nmap", "-Pn", "-T4", port_arg, "-oX", "-", host,
    ]
    result = _run_docker(cmd, "nmap")
    if result.returncode != 0:
        raise ToolError(f"nmap failed (exit {result.returncode}): {result.stderr[-2000:]}")

    return _parse_nmap_xml(result.stdout, host)


def _parse_nmap_xml(xml_text: str, host: str) -> list[dict]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ToolError(f"could not parse nmap output: {exc}") from exc

    findings = []
    for port_el in root.findall(".//port"):
        state_el = port_el.find("state")
        if state_el is None or state_el.get("state") != "open":
            continue
        service_el = port_el.find("service")
        service = service_el.get("name", "") if service_el is not None else ""
        product = service_el.get("product", "") if service_el is not None else ""
        portid = port_el.get("portid")
        protocol = port_el.get("protocol")
        findings.append(
            {
                "source_tool": "nmap",
                "severity": "info",
                "title": f"open {protocol}/{portid} ({service})",
                "description": f"{product}".strip() or f"{service} on {host}",
                "file_path": None,
                "line": None,
            }
        )
    return findings
