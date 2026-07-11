"""Tool Orchestrator (Phase 2) — docs/MVP.md #4.

Coordinates external recon/scan tools behind one interface so the Agent
Core never shells out directly, normalizes every tool's output to one
finding schema, and enforces the scope gate per invocation.

The pipeline is a declarative list of stages, not a hardcoded if/else
chain — adding, removing, or reordering a tool is a data change here, not a
new branch in the run function. Each stage still runs independently: one
tool failing (ToolError) or being denied scope (ScopeDenied) doesn't stop
the rest of the pipeline, it's recorded as a warning instead.
"""

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from api.scope import ACTIVE_SCAN, PASSIVE_RECON, ScopeDenied, require_authorized, resolve_for_container
from api.tool_router import ToolError, run_httpx, run_nmap


@dataclass(frozen=True)
class ToolStage:
    name: str
    action_class: str  # passive-recon | active-scan — see docs/SECURITY_AND_AUTHORIZATION.md
    runner: Callable[[str], list[dict]]


# The chain a scan runs. To add subfinder/katana/nuclei/ffuf/dalfox/sqlmap
# later, add a ToolStage here and a matching run_* in tool_router.py —
# nothing else in this module changes.
PIPELINE: list[ToolStage] = [
    ToolStage(name="httpx", action_class=PASSIVE_RECON, runner=run_httpx),
    ToolStage(name="nmap", action_class=ACTIVE_SCAN, runner=run_nmap),
]


def run_pipeline(session: Session, target: str) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    warnings: list[str] = []
    container_target = resolve_for_container(target)

    for stage in PIPELINE:
        try:
            require_authorized(session, target, stage.action_class)
        except ScopeDenied as exc:
            warnings.append(f"{stage.name}: skipped — {exc}")
            continue

        try:
            findings.extend(stage.runner(container_target))
        except ToolError as exc:
            warnings.append(f"{stage.name}: {exc}")

    return findings, warnings
