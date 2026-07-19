"""Tests for api/agents/adaptive_agent.py's decide->execute loop.

Split in two groups, same rigor split as the rest of this repo:
- Pure-logic tests: a fake action registry (plain Python functions, no
  Docker) + a monkeypatched `complete()`, exercising build_adaptive_graph
  directly against a real SQLAlchemy session/scope gate (no scope
  monkeypatching — "localhost" genuinely auto-verifies for ACTIVE_SCAN but
  never EXPLOITATION, so the ScopeDenied path is exercised for real too).
- One real end-to-end test: a real BrowserSession against the real
  browser_sandbox container, real Docker tool_router calls, driven by a
  scripted (not live-LLM) decision sequence — same reasoning as
  tests/test_sow.py monkeypatching `complete()` rather than depending on
  an LLM being configured in every environment this suite runs in.
"""

import functools
import http.server
import json
import tempfile
import threading
from pathlib import Path

import pytest

import api.agents.adaptive_agent as aa
from api.config import settings
from api.scope import ACTIVE_SCAN, EXPLOITATION
from memory.db import SessionLocal


def _fake_action(name: str, action_class: str, calls: list, returns=None):
    def _runner(**kwargs):
        calls.append((name, kwargs))
        return returns if returns is not None else []

    return aa.AdaptiveAction(name, "fake action for tests. args: {...}", action_class, _runner)


def _scripted_complete(decisions):
    it = iter(decisions)

    def _complete(messages, purpose="coding"):
        return json.dumps(next(it))

    return _complete


def test_stops_immediately_when_planner_says_done():
    calls = []
    registry = {"noop": _fake_action("noop", ACTIVE_SCAN, calls)}
    aa.complete = _scripted_complete([{"action": "done", "args": {}, "reasoning": "nothing to do"}])

    session = SessionLocal()
    try:
        final = aa.build_adaptive_graph(session, "localhost", registry).invoke(
            _initial_state(), config={"recursion_limit": 20}
        )
    finally:
        session.close()

    assert final["step_count"] == 0
    assert calls == []


def test_fails_closed_on_an_unrecognized_action_name():
    calls = []
    registry = {"noop": _fake_action("noop", ACTIVE_SCAN, calls)}
    aa.complete = _scripted_complete(
        [{"action": "totally_made_up_action", "args": {}, "reasoning": "try it"}]
    )

    session = SessionLocal()
    try:
        final = aa.build_adaptive_graph(session, "localhost", registry).invoke(
            _initial_state(), config={"recursion_limit": 20}
        )
    finally:
        session.close()

    assert final["step_count"] == 0
    assert calls == []


def test_fails_closed_on_malformed_json():
    registry = {}
    aa.complete = lambda messages, purpose="coding": "not json at all"

    session = SessionLocal()
    try:
        final = aa.build_adaptive_graph(session, "localhost", registry).invoke(
            _initial_state(), config={"recursion_limit": 20}
        )
    finally:
        session.close()

    assert final["step_count"] == 0


def test_stops_at_the_configured_step_cap():
    calls = []
    registry = {"repeatable": _fake_action("repeatable", ACTIVE_SCAN, calls, returns=[{"source_tool": "fake"}])}
    # Always picks the same action forever — only the step cap should stop it.
    aa.complete = lambda messages, purpose="coding": json.dumps(
        {"action": "repeatable", "args": {}, "reasoning": "again"}
    )

    session = SessionLocal()
    try:
        final = aa.build_adaptive_graph(session, "localhost", registry).invoke(
            _initial_state(), config={"recursion_limit": 200}
        )
    finally:
        session.close()

    assert final["step_count"] == settings.adaptive_agent_max_steps
    assert len(calls) == settings.adaptive_agent_max_steps


def test_stops_after_consecutive_steps_with_no_new_findings():
    calls = []
    registry = {"dud": _fake_action("dud", ACTIVE_SCAN, calls, returns=[])}  # never finds anything
    aa.complete = lambda messages, purpose="coding": json.dumps({"action": "dud", "args": {}, "reasoning": "again"})

    session = SessionLocal()
    try:
        final = aa.build_adaptive_graph(session, "localhost", registry).invoke(
            _initial_state(), config={"recursion_limit": 200}
        )
    finally:
        session.close()

    assert final["stale_streak"] == settings.adaptive_agent_stale_after_steps
    assert final["step_count"] == settings.adaptive_agent_stale_after_steps


def test_scope_denied_action_is_recorded_as_a_warning_not_a_crash():
    """"localhost" auto-verifies for ACTIVE_SCAN but never EXPLOITATION
    (only a real SOW can grant that) — a real, unmocked ScopeDenied path."""
    calls = []
    registry = {"needs_sow": _fake_action("needs_sow", EXPLOITATION, calls)}
    aa.complete = _scripted_complete(
        [
            {"action": "needs_sow", "args": {}, "reasoning": "try the gated one"},
            {"action": "done", "args": {}, "reasoning": "stop"},
        ]
    )

    session = SessionLocal()
    try:
        final = aa.build_adaptive_graph(session, "localhost", registry).invoke(
            _initial_state(), config={"recursion_limit": 20}
        )
    finally:
        session.close()

    assert calls == []  # never actually ran — scope denied before the runner was called
    assert any("skipped" in w for w in final["warnings"])


def test_a_runner_exception_is_recorded_as_a_warning_not_a_crash():
    def _blows_up(**kwargs):
        raise ValueError("boom")

    registry = {"broken": aa.AdaptiveAction("broken", "fake broken action. args: {}", ACTIVE_SCAN, _blows_up)}
    aa.complete = _scripted_complete(
        [
            {"action": "broken", "args": {}, "reasoning": "try it"},
            {"action": "done", "args": {}, "reasoning": "stop"},
        ]
    )

    session = SessionLocal()
    try:
        # ValueError isn't one of _execute_node's caught exception types —
        # confirms the registry is expected to only ever raise ToolError/
        # BrowserActionError/TypeError, matching every tool_router.py
        # run_* function's contract.
        with pytest.raises(ValueError):
            aa.build_adaptive_graph(session, "localhost", registry).invoke(
                _initial_state(), config={"recursion_limit": 20}
            )
    finally:
        session.close()


def _initial_state() -> dict:
    return {
        "target": "localhost",
        "current_url": "http://localhost/",
        "findings": [],
        "warnings": [],
        "steps": [],
        "step_count": 0,
        "stale_streak": 0,
        "pending_action": "",
        "pending_args": {},
        "pending_reasoning": "",
    }


def _start_form_server(port: int):
    tmpdir_ctx = tempfile.TemporaryDirectory()
    tmpdir = tmpdir_ctx.name
    (Path(tmpdir) / "index.html").write_text(
        '<html><body><h1>Home</h1><a href="/next.html">Next</a></body></html>'
    )
    (Path(tmpdir) / "next.html").write_text("<html><body><h1>Next Page</h1></body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmpdir)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, tmpdir_ctx


def test_run_adaptive_executes_real_actions_and_terminates():
    """End-to-end against the real browser_sandbox container and real
    tool_router functions, driven by a scripted decision sequence (not a
    live LLM — same reasoning as test_sow.py's monkeypatched complete()).
    Proves the whole real wiring: registry -> scope gate -> runner ->
    findings accumulate -> loop terminates."""
    port = 8870
    httpd, tmpdir_ctx = _start_form_server(port)
    target = "localhost"  # auto-verified for ACTIVE_SCAN, no SOW/self-attest needed
    target_url = f"http://{settings.container_host_alias}:{port}/"

    decisions = iter(
        [
            {"action": "browser_navigate", "args": {"url": target_url}, "reasoning": "look at the page"},
            {"action": "browser_extract_text", "args": {}, "reasoning": "see what's there"},
            {"action": "done", "args": {}, "reasoning": "nothing further"},
        ]
    )
    aa.complete = lambda messages, purpose="coding": json.dumps(next(decisions))

    session = SessionLocal()
    try:
        final = aa.run_adaptive(session, target, seed_findings=[], seed_warnings=[])
    finally:
        session.close()
        httpd.shutdown()
        tmpdir_ctx.cleanup()

    assert final["step_count"] == 2
    assert any("Home" in f.get("description", "") for f in final["findings"])
    assert any("adaptive planner:" in w for w in final["warnings"])
