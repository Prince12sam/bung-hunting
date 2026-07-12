# Agent Roster

A Master Agent routes each request to one or more specialists. Each
specialist has a narrow tool allowlist and system prompt — it should not
know how to do another specialist's job.

## MVP agents (built now)

### Coding Agent
- **Tools:** filesystem read/write, semgrep, test runner, git.
- **Flow:** read code → find issues → explain → patch → run tests → commit.
  PR creation is an explicit opt-in per repo, never a default action
  (docs/REVIEW.md point 6).
- **Backs:** `security fix`, `security analyze`, VS Code extension.

### Pentest Agent
- **Tools:** the Tool Orchestrator's active chain (nmap, httpx, subfinder,
  katana, nuclei, ffuf, dalfox, sqlmap) — every call gated by scope
  verification. Burp Suite integration (docs/ROADMAP.md Phase 4 item 2) is
  a planned addition to this same chain, same gate.
- **Flow:** recon → surface mapping → targeted active testing → findings to
  Memory.
- **Posture:** detection, not exploitation-to-completion — today's active
  tools run at conservative settings that report a likely issue rather than
  confirm it by fully exploiting it. A stricter-gated opt-in exploitation
  tier is docs/ROADMAP.md Phase 4 item 10, not part of this agent as built.
- **Backs:** `security scan`.

### Browser Agent
- **Tools:** passive page inspection (headers, CSP, cookies, storage, CORS,
  robots.txt/sitemap, JS parsing for keys/secrets, fingerprinting, WAF
  detection) by default; active checks (GraphQL introspection, endpoint
  fuzzing) only behind the scope gate + explicit user action.
- **Flow:** on page load, run passive checks, surface a summary, offer next
  active step as an explicit choice (not an implicit auto-run).
- **Backs:** browser extension.

## Deferred agents (post-MVP, see docs/ROADMAP.md for sequencing/rationale)

- **Report Agent** — turns Memory findings into a reproducible report with
  evidence links; only worth building once there's enough real finding
  volume flowing through Memory to report on.
- **Browser Automation Agent** — Playwright-driven authenticated testing:
  login, click, fill forms, navigate, capture traffic. Gated by the
  `local-automation` action class (docs/SECURITY_AND_AUTHORIZATION.md) on
  top of the normal target-scope check, since it acts on a real
  authenticated session, not just a passive page load. Distinct from the
  MVP Browser Agent above (which is passive-only, in-browser-extension).
- **Bug Hunting Agent** — orchestrates Pentest + Browser Automation (+ Burp
  Suite) agents against a defined bug-bounty scope with a checkpoint before
  any active submission. Waits on those to exist to compose.
- **Malware/Document Analysis Sandbox Agent** — opens and detonates
  suspicious files (documents, binaries) in an isolated sandbox only, never
  given network access to the host machine. This is the one place "open a
  document" is safe by construction — the document never reaches a real
  filesystem or application.
- **Local Automation / Computer-Use Agent** — general desktop control:
  launching arbitrary applications, opening arbitrary files, driving GUIs
  beyond what the sandboxed agent above or a Playwright browser session
  cover. Deliberately last to build: highest risk, most exposed to prompt
  injection (a malicious page/document tricking the agent into a real
  local action), and needs the `local-automation` grant mechanism actually
  designed first (docs/ROADMAP.md open decisions), not just gated in
  principle.
- **Cloud Agent** — AWS/Azure/GCP misconfiguration review, IaC (Terraform/
  Kubernetes) review.
- **IAM Agent** — Active Directory and identity/access assessments.
- **SOC Agent** — log/alert triage, correlation, playbook suggestions.
- **OSINT Agent** — public-source enumeration, kept strictly passive.
- **Reverse Engineering Agent** — static/dynamic binary analysis, sandboxed;
  overlaps with the Malware/Document Sandbox Agent above and may merge with
  it rather than staying separate.

## Master Agent

Routing only — given a request, decides which specialist(s) handle it and in
what order, then hands off to the Agent Core's Planner. It does not itself
call tools.
