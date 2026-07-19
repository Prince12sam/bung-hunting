"""Adaptive planning loop — an optional extra phase after the fixed
PIPELINE (api/orchestrator.py), not a replacement for it. `scan --adaptive`
runs this afterward, seeded with the fixed pipeline's findings, and lets
an LLM decide what to try next based on what's been found so far —
following an interesting lead, trying a discovered login form, etc. — the
things a fixed, deterministic tool order can't do.

Safety is the same standing rule as everywhere else in this codebase:
- A closed, pre-vetted action registry (_static_tool_actions/_browser_actions
  below) — the LLM picks *which* vetted action runs and with what
  arguments, never arbitrary code, matching the "only vetted Metasploit
  auxiliary/scanner modules" restriction already in place for
  run_msf_http_version.
- Every action re-checks api/scope.py's require_authorized at execute
  time, independent of the planner's decision — no bypass.
- State-changing browser actions (click/fill) need the EXPLOITATION tier
  (SOW-only), the same boundary already chosen for sqlmap's
  confirm_impact — interacting in a way that could change target state
  needs the strongest authorization, not a self-attestation.
- A hard step cap plus early-stop-when-nothing-new bounds cost/runtime.
"""

import json
from dataclasses import dataclass
from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from api import scan_status
from api.browser_client import BrowserActionError, BrowserSession
from api.config import settings
from api.llm_router import LLMUnavailable, complete
from api.orchestrator import _as_url, resolve_for_container
from api.scope import ACTIVE_SCAN, EXPLOITATION, ScopeDenied, has_authorization, require_authorized
from api.tool_router import (
    ToolError,
    run_dalfox,
    run_feroxbuster,
    run_ffuf,
    run_nikto,
    run_nuclei,
    run_sqlmap,
    run_testssl,
    run_wpscan,
)

DONE = "done"


@dataclass(frozen=True)
class AdaptiveAction:
    name: str
    description: str  # shown to the LLM verbatim — must name its exact kwargs
    action_class: str  # PASSIVE_RECON | ACTIVE_SCAN | EXPLOITATION
    runner: Callable[..., list[dict]]
    escalation_class: str | None = None  # same meaning as ToolStage.escalation_class


def _static_tool_actions() -> dict[str, AdaptiveAction]:
    """The subset of tool_router.py's tools suited to targeted, adaptive
    follow-up (deeper/URL-specific checks) rather than broad enumeration —
    subdomain/host discovery is already done once by the fixed pipeline's
    phase 1, re-running it here on every step would be wasteful."""
    return {
        "nuclei": AdaptiveAction(
            "nuclei",
            "Template-based vulnerability scan of a specific URL. args: {'url': str}",
            ACTIVE_SCAN,
            run_nuclei,
        ),
        "nikto": AdaptiveAction(
            "nikto",
            "Web server hygiene/config scanner. args: {'url': str}",
            ACTIVE_SCAN,
            run_nikto,
        ),
        "dalfox": AdaptiveAction(
            "dalfox",
            "XSS scanner for a specific URL. args: {'url': str}",
            ACTIVE_SCAN,
            run_dalfox,
        ),
        "testssl": AdaptiveAction(
            "testssl",
            "TLS/SSL configuration + known-vuln checks (https:// URLs only). args: {'url': str}",
            ACTIVE_SCAN,
            run_testssl,
        ),
        "wpscan": AdaptiveAction(
            "wpscan",
            "WordPress plugin/theme/user enumeration. args: {'url': str}",
            ACTIVE_SCAN,
            run_wpscan,
        ),
        "ffuf": AdaptiveAction(
            "ffuf",
            "Directory/file fuzzing against a specific URL. args: {'url': str}",
            ACTIVE_SCAN,
            run_ffuf,
        ),
        "feroxbuster": AdaptiveAction(
            "feroxbuster",
            "Recursive content discovery against a specific URL. args: {'url': str}",
            ACTIVE_SCAN,
            run_feroxbuster,
        ),
        "sqlmap": AdaptiveAction(
            "sqlmap",
            "SQL injection detection (and, only if this engagement's SOW authorized "
            "exploitation, confirmation of real impact) against a specific URL. args: {'url': str}",
            ACTIVE_SCAN,
            run_sqlmap,
            escalation_class=EXPLOITATION,
        ),
    }


def _browser_actions(browser: BrowserSession) -> dict[str, AdaptiveAction]:
    """Bound to one live BrowserSession for the whole adaptive run — state
    (which page it's on, cookies) must persist across steps, unlike the
    stateless one-shot tool_router functions above."""
    return {
        "browser_navigate": AdaptiveAction(
            "browser_navigate",
            "Navigate the sandboxed browser to a URL. args: {'url': str}",
            ACTIVE_SCAN,
            browser.navigate,
        ),
        "browser_extract_text": AdaptiveAction(
            "browser_extract_text",
            "Extract visible text from the current sandboxed-browser page. args: {}",
            ACTIVE_SCAN,
            browser.extract_text,
        ),
        "browser_extract_forms": AdaptiveAction(
            "browser_extract_forms",
            "List forms (action/method/fields) on the current sandboxed-browser page. args: {}",
            ACTIVE_SCAN,
            browser.extract_forms,
        ),
        "browser_screenshot": AdaptiveAction(
            "browser_screenshot",
            "Screenshot the current sandboxed-browser page as report evidence. args: {}",
            ACTIVE_SCAN,
            browser.screenshot,
        ),
        # State-changing — gated at EXPLOITATION (SOW-only), same boundary
        # already chosen for sqlmap's confirm_impact.
        "browser_click": AdaptiveAction(
            "browser_click",
            "Click a link/button in the sandboxed browser by visible text or CSS "
            "selector. State-changing. args: {'text_or_selector': str}",
            EXPLOITATION,
            browser.click,
        ),
        "browser_fill": AdaptiveAction(
            "browser_fill",
            "Fill a form field in the sandboxed browser. State-changing. "
            "args: {'selector': str, 'value': str}",
            EXPLOITATION,
            browser.fill,
        ),
    }


class AdaptiveState(TypedDict):
    target: str
    current_url: str
    findings: list[dict]
    warnings: list[str]
    steps: list[dict]  # [{"action": str, "args": dict, "reasoning": str}, ...]
    step_count: int
    stale_streak: int
    # The most recent, not-yet-executed decision — set by the "decide"
    # node, consumed by the "execute" node. Not meaningful outside one
    # decide->execute cycle.
    pending_action: str
    pending_args: dict
    pending_reasoning: str


_DECIDE_PROMPT = """You are an adaptive pentest planner. Given the actions available below and \
what's been found so far, decide the single most valuable next action — or declare the \
engagement done for now.

Target: {target}
Current browser URL: {current_url}

Available actions:
{actions_desc}

Findings so far ({finding_count} total, newest last):
{findings_summary}

Steps already taken this run:
{steps_summary}

Respond with ONLY a JSON object, no markdown fences, no explanation:
{{"action": "<one of the action names above, or \"done\">", "args": {{...matching that action's documented args...}}, "reasoning": "one sentence"}}

Pick "done" once nothing further seems worth trying, or if no action is clearly more useful \
than what's already been done.
"""


def _describe_actions(registry: dict[str, AdaptiveAction]) -> str:
    return "\n".join(f"- {a.name} ({a.action_class}): {a.description}" for a in registry.values())


def _summarize_findings(findings: list[dict]) -> str:
    if not findings:
        return "(none yet)"
    return "\n".join(f"- [{f.get('severity')}] {f.get('title')}" for f in findings[-20:])


def _summarize_steps(steps: list[dict]) -> str:
    if not steps:
        return "(none yet)"
    return "\n".join(f"- {s['action']}({s['args']}) — {s['reasoning']}" for s in steps[-10:])


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _decide(state: AdaptiveState, registry: dict[str, AdaptiveAction]) -> dict:
    """Returns {"action": name-or-"done", "args": dict, "reasoning": str}.
    Fails closed to "done" on anything malformed or unrecognized — never
    retried into an unbounded loop, never allowed to name something
    outside the registry."""
    prompt = _DECIDE_PROMPT.format(
        target=state["target"],
        current_url=state["current_url"],
        actions_desc=_describe_actions(registry),
        finding_count=len(state["findings"]),
        findings_summary=_summarize_findings(state["findings"]),
        steps_summary=_summarize_steps(state["steps"]),
    )
    try:
        raw = complete([{"role": "user", "content": prompt}], purpose="coding")
    except LLMUnavailable:
        return {"action": DONE, "args": {}, "reasoning": "LLM unavailable"}

    try:
        decision = json.loads(_strip_markdown_fences(raw))
    except json.JSONDecodeError:
        return {"action": DONE, "args": {}, "reasoning": "planner response was not valid JSON"}

    action_name = decision.get("action")
    if action_name != DONE and action_name not in registry:
        return {"action": DONE, "args": {}, "reasoning": f"planner named an unrecognized action: {action_name!r}"}

    return {
        "action": action_name,
        "args": decision.get("args") or {},
        "reasoning": str(decision.get("reasoning", "")),
    }


def build_adaptive_graph(session: Session, target: str, registry: dict[str, AdaptiveAction]):
    """A real decide->execute cycle via LangGraph's add_conditional_edges —
    not used anywhere else in this codebase yet (api/agents/pentest_agent.py
    and coding_agent.py's graphs are strictly linear), but the standard way
    LangGraph expresses a loop. `session`/`target`/`registry` are captured
    by closure, the same way api/agents/pentest_agent.py's `_scan_node`
    closes over `session` — LangGraph state stays plain data (dicts/lists/
    strings), never a live resource handle like a DB session or browser
    connection.
    """

    def _decide_node(state: AdaptiveState) -> AdaptiveState:
        scan_status.set_stage(
            target, "adaptive: deciding next step", state["step_count"] + 1, settings.adaptive_agent_max_steps
        )
        decision = _decide(state, registry)
        return {
            **state,
            "pending_action": decision["action"],
            "pending_args": decision["args"],
            "pending_reasoning": decision["reasoning"],
        }

    def _execute_node(state: AdaptiveState) -> AdaptiveState:
        action = registry[state["pending_action"]]
        scan_status.set_stage(
            target, f"adaptive: {action.name}", state["step_count"] + 1, settings.adaptive_agent_max_steps
        )
        findings = list(state["findings"])
        warnings = list(state["warnings"])
        findings_before = len(findings)

        try:
            require_authorized(session, target, action.action_class)
            kwargs = dict(state["pending_args"])
            if action.escalation_class:
                kwargs["confirm_impact"] = has_authorization(session, target, action.escalation_class)
            findings.extend(action.runner(**kwargs))
            current_url = kwargs.get("url", state["current_url"])
        except ScopeDenied as exc:
            warnings.append(f"adaptive: {action.name} skipped — {exc}")
            current_url = state["current_url"]
        except (ToolError, BrowserActionError, TypeError) as exc:
            warnings.append(f"adaptive: {action.name} failed — {exc}")
            current_url = state["current_url"]

        stale_streak = 0 if len(findings) > findings_before else state["stale_streak"] + 1
        steps = state["steps"] + [
            {"action": action.name, "args": state["pending_args"], "reasoning": state["pending_reasoning"]}
        ]
        return {
            **state,
            "current_url": current_url,
            "findings": findings,
            "warnings": warnings,
            "steps": steps,
            "step_count": state["step_count"] + 1,
            "stale_streak": stale_streak,
        }

    def _should_continue(state: AdaptiveState) -> str:
        if state["pending_action"] == DONE:
            return END
        if state["step_count"] >= settings.adaptive_agent_max_steps:
            return END
        if state["stale_streak"] >= settings.adaptive_agent_stale_after_steps:
            return END
        return "execute"

    graph = StateGraph(AdaptiveState)
    graph.add_node("decide", _decide_node)
    graph.add_node("execute", _execute_node)
    graph.set_entry_point("decide")
    graph.add_conditional_edges("decide", _should_continue, {"execute": "execute", END: END})
    graph.add_edge("execute", "decide")
    return graph.compile()


def run_adaptive(session: Session, target: str, seed_findings: list[dict], seed_warnings: list[str]) -> AdaptiveState:
    """Runs the adaptive loop to completion (step cap, stale-detection, or
    the planner declaring "done") and returns the final state. `target` is
    the same identifier the fixed pipeline (api/orchestrator.py) already
    scope-checked — every action here re-checks scope independently
    anyway, this doesn't rely on that prior check."""
    root_url = _as_url(resolve_for_container(target))

    with BrowserSession() as browser:
        registry = {**_static_tool_actions(), **_browser_actions(browser)}
        graph = build_adaptive_graph(session, target, registry)

        initial_state: AdaptiveState = {
            "target": target,
            "current_url": root_url,
            "findings": list(seed_findings),
            "warnings": list(seed_warnings),
            "steps": [],
            "step_count": 0,
            "stale_streak": 0,
            "pending_action": "",
            "pending_args": {},
            "pending_reasoning": "",
        }
        # LangGraph's default recursion_limit (25 node-visits) is a much
        # blunter, structural backstop distinct from adaptive_agent_max_steps
        # (which counts *executed actions*, not node visits) — set well
        # above what max_steps could ever reach (each step is 2 node
        # visits: decide, execute) so max_steps is always what actually
        # stops the run, not this.
        try:
            final_state = graph.invoke(
                initial_state, config={"recursion_limit": settings.adaptive_agent_max_steps * 4 + 10}
            )
        finally:
            scan_status.clear(target)
        final_state["warnings"].append(f"adaptive planner: {_stop_reason(final_state)}")
        return final_state


def _stop_reason(state: AdaptiveState) -> str:
    if state["pending_action"] == DONE:
        return f"done — {state['pending_reasoning']}"
    if state["step_count"] >= settings.adaptive_agent_max_steps:
        return f"stopped at the {settings.adaptive_agent_max_steps}-step cap"
    if state["stale_streak"] >= settings.adaptive_agent_stale_after_steps:
        return f"stopped — {state['stale_streak']} consecutive steps with no new findings"
    return "stopped for an unrecognized reason"  # unreachable in practice — _should_continue covers every case
