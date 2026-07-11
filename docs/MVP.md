# MVP Scope

Six components, built in this order. Each one should be independently usable
before the next starts — no component waits on all the others to be "done."

```
Phase 1  Agent Core  ─┐
Phase 1  Memory       ─┼─ these three form the usable end-to-end loop
Phase 1  CLI          ─┘
Phase 2  Tool Orchestrator  (plugs into the Phase 1 loop)
Phase 3  VS Code Extension  (thin client over Agent Core)
Phase 3  Browser Extension  (thin client over Agent Core)
```

Rationale for this order: docs/REVIEW.md, point 4.

## 1. Agent Core

FastAPI service exposing a single agent loop (LangGraph) with:

- **Planner** — turns a natural-language or CLI command into a task graph.
- **Context Manager** — assembles the working context (project files, prior
  findings, target scope) per step, respecting the model's context budget.
- **Tool Router** — maps a planned step to a concrete tool call (local
  function, subprocess, or MCP-style tool) and enforces the authorization
  gate (docs/SECURITY_AND_AUTHORIZATION.md) before anything active runs.
- **LLM Router** — picks a model per step (cloud vs local) based on task
  type, data sensitivity, and availability; retries/falls back on failure.

**Acceptance criteria:** given a single CLI command, the core can plan a
multi-step task, call at least one real tool, and return a structured result
— without a human manually sequencing the steps.

## 2. Memory

Postgres + pgvector, one schema, no parallel vector store (docs/REVIEW.md,
point 3). Tracks:

- Projects / targets (scope-verified or not)
- Findings (with source tool, timestamp, evidence path)
- Notes and prior agent reasoning (for continuity across sessions)
- Credentials — reference/pointer only, actual secret material lives in a
  local encrypted vault, not in the vector store (docs/SECURITY_AND_AUTHORIZATION.md)

**Acceptance criteria:** a finding recorded in one CLI session is retrievable
and correctly summarized in a later, separate session.

## 3. CLI

Typer + Rich. Three verbs to start:

```
security scan <target>     # orchestrator-driven recon → active chain, gated by scope
security analyze <path>     # static review of local code, no network activity
security fix <path>         # analyze + patch + test, PR creation is opt-in per repo
```

**Acceptance criteria:** all three verbs work against a real (owned/lab)
target and a real local repo, end to end, with output a human can act on
without reading raw tool logs.

## 4. Tool Orchestrator — status: slice 1 done (api/orchestrator.py)

Coordinates external tools behind one interface so the Agent Core never
shells out directly. Responsibilities:

- Normalizes each tool's output into one finding schema.
- Enforces the scope/authorization gate per invocation, not just per session
  (api/scope.py — every stage calls `require_authorized` before it runs;
  denials are recorded as warnings, not silent skips).
- Sandboxes every tool in a container (Docker) — nothing shells out to a
  host-installed binary.

**Shipped in slice 1:** httpx (passive HTTP fingerprinting) + nmap (active
TCP scan), a declarative `PIPELINE` list in api/orchestrator.py (adding a
tool is a data change, not a new if/else branch), and the scope model from
docs/SECURITY_AND_AUTHORIZATION.md — local/private targets auto-verify,
everything else needs `es verify-target` (file-token method) before active
stages run. Verified end-to-end against `localhost` (real open ports
found) and a scope-denial test against an unverified third-party domain
(confirms the gate actually blocks, not just warns).

**Deferred to a later slice:** subfinder, katana, nuclei, ffuf, dalfox,
sqlmap. Each is: add a `run_x` in api/tool_router.py + a `ToolStage` entry
in api/orchestrator.py's `PIPELINE` — the pattern is proven, this is now
additive work, not architecture work.

**Acceptance criteria (met for the shipped subset):** `es scan` on a
localhost/lab target runs the pipeline and every finding lands in Memory
with a consistent schema, regardless of which underlying tool produced it;
an unauthorized target is refused rather than scanned.

## 5. VS Code Extension

Thin client: sends `analyze` / `fix` requests to the running Agent Core,
renders findings and diffs inline. No logic that isn't already in the CLI.

## 6. Browser Extension

Passive-first: headers, CSP, cookies, storage, CORS, robots.txt/sitemap,
fingerprinting run automatically and read-only. Anything that would actively
probe the site (GraphQL schema enumeration, endpoint fuzzing) requires the
scope gate and an explicit user action, not just page load.

## Explicitly deferred past MVP

SOC Agent, Cloud Agent, IAM Agent, OSINT Agent, Malware/RE Agent, Report
Agent as a distinct surface, Playwright-driven authenticated browsing,
desktop app, Firefox extension, voice commands. See docs/ROADMAP.md for
sequencing after MVP.
