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
from typing import Callable, Literal

from sqlalchemy.orm import Session

from api import scan_status
from api.scope import ACTIVE_SCAN, PASSIVE_RECON, ScopeDenied, require_authorized, resolve_for_container
from api.tool_router import (
    ToolError,
    run_dalfox,
    run_ffuf,
    run_httpx,
    run_katana,
    run_nmap,
    run_nuclei,
    run_sqlmap,
    run_subfinder,
)

TargetForm = Literal["host", "url"]


@dataclass(frozen=True)
class ToolStage:
    name: str
    action_class: str  # passive-recon | active-scan — see docs/SECURITY_AND_AUTHORIZATION.md
    runner: Callable[[str], list[dict]]
    target_form: TargetForm = "host"  # host-only tools (nmap, subfinder) vs URL tools (the rest)


# The chain a scan runs. Adding a tool is a data change here plus a matching
# run_* in tool_router.py — nothing else in this module changes.
PIPELINE: list[ToolStage] = [
    ToolStage(name="httpx", action_class=PASSIVE_RECON, runner=run_httpx, target_form="host"),
    ToolStage(name="subfinder", action_class=PASSIVE_RECON, runner=run_subfinder, target_form="host"),
    ToolStage(name="katana", action_class=PASSIVE_RECON, runner=run_katana, target_form="url"),
    ToolStage(name="nmap", action_class=ACTIVE_SCAN, runner=run_nmap, target_form="host"),
    ToolStage(name="nuclei", action_class=ACTIVE_SCAN, runner=run_nuclei, target_form="url"),
    ToolStage(name="ffuf", action_class=ACTIVE_SCAN, runner=run_ffuf, target_form="url"),
    ToolStage(name="dalfox", action_class=ACTIVE_SCAN, runner=run_dalfox, target_form="url"),
    ToolStage(name="sqlmap", action_class=ACTIVE_SCAN, runner=run_sqlmap, target_form="url"),
]


def _as_host(target: str) -> str:
    return target.split("://", 1)[-1]


def _as_url(target: str) -> str:
    return target if "://" in target else f"http://{target}"


def run_pipeline(session: Session, target: str) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    warnings: list[str] = []
    container_target = resolve_for_container(target)
    host_form = _as_host(container_target)
    url_form = _as_url(container_target)

    try:
        for i, stage in enumerate(PIPELINE, start=1):
            try:
                require_authorized(session, target, stage.action_class)
            except ScopeDenied as exc:
                warnings.append(f"{stage.name}: skipped — {exc}")
                continue

            scan_status.set_stage(target, stage.name, i, len(PIPELINE))
            stage_target = host_form if stage.target_form == "host" else url_form
            try:
                findings.extend(stage.runner(stage_target))
            except ToolError as exc:
                warnings.append(f"{stage.name}: {exc}")
    finally:
        scan_status.clear(target)

    return findings, warnings
