# Long-Term Vision

This is the full picture Es is aimed at eventually. It is **not**
current scope — see docs/MVP.md for what's actually being built, and
docs/ROADMAP.md for sequencing. Kept here so later phases have a fixed
reference instead of relying on memory of the original pitch.

## One-line pitch

Combine Claude Code / GitHub Copilot / Cursor / OpenHands (AI coding) with
Kali Linux / Burp Suite / Nuclei (security tooling) into one local,
multi-agent platform, orchestrated by an LLM router with local-model
fallback.

## Surfaces

- CLI
- VS Code extension
- Browser extension (Chrome, later Firefox)
- Desktop app (Tauri) — later phase
- Direct integrations: Burp Suite, Docker, Kali, Git, local APIs

## Full agent roster

Master Agent routing to: Coding, Pentest, Bug Hunting, Reverse Engineering,
SOC, Cloud, IAM, OSINT, Malware/Document Sandbox, Report, Browser, Local
Automation. Detail per agent, and which are MVP vs. deferred, in
docs/AGENTS.md; the last two (Malware/Document Sandbox, Local Automation)
are the "open documents/applications" capability split into a safe half
(sandboxed detonation, no host network) and a genuinely higher-risk half
(real desktop control), on purpose — see docs/SECURITY_AND_AUTHORIZATION.md's
`local-automation` action class for why they aren't one agent.

## Browser Agent — full passive check list

Headers, CSP, cookies, JWT, local/session storage, CORS, GraphQL, hidden
APIs, JS secrets, Firebase, Supabase, AWS/Azure keys, Stripe/Paystack,
debug endpoints, robots.txt, sitemap.xml, Swagger/OpenAPI, fingerprinting,
WAF detection — then offers active follow-ups (e.g. GraphQL schema
enumeration) as an explicit, gated next step, never automatic
(docs/SECURITY_AND_AUTHORIZATION.md).

## CLI Agent — full active chain

```
nmap → httpx → subfinder → katana → nuclei → ffuf → dalfox → sqlmap
→ Burp Suite → custom scripts → LLM analysis
```

The Tool Orchestrator (docs/MVP.md #4) decides the chain per target; the
user doesn't manually pick tools. Burp Suite integration (docs/ROADMAP.md
Phase 4 item 2) is a new Tool Orchestrator stage like any other — same
`run_x` + `ToolStage` pattern already proven for the 8 tools above, wired
to Burp's REST API (Professional/Enterprise) rather than a bare CLI. All
of today's active tools run at conservative/detection settings; a future
opt-in exploitation tier (docs/ROADMAP.md Phase 4 item 10) is a separate,
more strictly gated escalation, not something Burp's addition changes by
itself.

## Coding Agent — full flow

Read code → find vulnerabilities → explain → write patch → run tests →
git commit → (opt-in) create PR.

## Memory — full data model

Postgres + pgvector as the single store (docs/REVIEW.md point 3 explains why
this collapsed from three parallel stores): projects, targets, credentials
(reference only — see docs/SECURITY_AND_AUTHORIZATION.md), notes, findings,
exploits, reports, screenshots.

## Browser automation

Playwright-driven authenticated testing: login, click, fill forms, navigate,
capture traffic, analyze. This is powerful and also a real risk surface for
accidentally acting on a live account, so it's gated by the
`local-automation` action class (docs/SECURITY_AND_AUTHORIZATION.md) on top
of the normal target-scope check — an authenticated session needs its own
explicit grant, not just a verified domain. Scheduled as docs/ROADMAP.md
Phase 4 item 3, after Burp Suite integration (item 2) but before the Bug
Hunting Agent (item 4) that composes it with the Pentest Agent.

## Local Automation / Computer-Use Agent

The other half of "open documents/applications": general desktop control
beyond a sandboxed browser session or an isolated malware-detonation
chamber — launching arbitrary applications, opening arbitrary files,
driving GUIs. Deliberately the last agent in the roadmap
(docs/ROADMAP.md Phase 4 item 9): it's the highest-risk, most novel
capability here, and the one most exposed to prompt injection, since a
malicious page or document could try to trick the agent into taking a
real action on the user's actual desktop. Requires a concrete
`local-automation` grant design (docs/ROADMAP.md's open decisions) before
any implementation starts — the principle (same gate, extended; no
default-on; isolation and authorization are both required, neither
substitutes for the other) is decided, the mechanism isn't.

## Knowledge base

Continuously indexed, embedded locally: OWASP, MITRE ATT&CK, NIST, CVE,
ExploitDB, GitHub, HackTricks, PayloadsAllTheThings, PortSwigger, Microsoft/
AWS/Azure docs. Feeds the LLM Router's context for both Coding and Pentest
agents.

## Future features (unordered, all post-MVP)

- Voice commands ("Scan this application.")
- Autonomous bug bounty workflows with approval checkpoints
- Malware/document analysis sandbox (sandboxed, no host network access)
- General computer-use / desktop automation (docs/ROADMAP.md Phase 4 item 9
  — gated by the `local-automation` action class, not assumed safe because
  it's local)
- Burp Suite and similar tool integrations via the Tool Orchestrator
- Cloud misconfiguration analysis (AWS, Azure, GCP)
- Infrastructure-as-Code review (Terraform, Kubernetes)
- Active Directory and IAM assessments
- SOC investigation workflows
- Automated report generation with reproducible evidence
- Team collaboration and shared knowledge

## Full original folder structure (target shape, not current)

```
security-ai/
    agents/       (pentest, coding, browser, reverse, soc, cloud, ...)
    tools/        (nuclei, burp, sqlmap, ffuf, katana, subfinder, ...)
    llm/
    memory/
    browser-extension/
    cli/
    api/
    ui/
    docker/
    docs/
```

MVP builds a subset of this (Agent Core lives under `api/` + `agents/`
narrowed to Coding/Pentest/Browser; `tools/` limited to the MVP chain;
`memory/` is Postgres+pgvector only) — see docs/TECH_STACK.md.
