# Roadmap

## Phase 0 — Documentation — done

This doc set.

## Phase 1 — Usable loop — done

Agent Core + Memory + CLI, working end to end against real (owned/lab)
targets and real local repos. `es analyze` / `es fix` verified end-to-end
(docs/MVP.md #1-3). Remaining gap: no LLM provider configured yet, so
`analyze` summaries and `fix` patch generation are inert until an API key
or local model is set (docs/GETTING_STARTED.md) — everything else works
without one.

## Phase 2 — Tool Orchestrator — done

Recon → active chain behind the scope gate. Full pipeline built and
verified end-to-end: httpx, subfinder, katana, nmap, nuclei, ffuf, dalfox,
sqlmap — see docs/MVP.md #4 for exactly what was proven for each. `es scan`
on a lab/authorized target runs the whole chain; an unauthorized target is
refused, not scanned.

## Phase 3 — Thin clients

VS Code extension, Chrome extension. Both call the same Agent Core the CLI
already uses — no new agent logic introduced here.

## Phase 4 — Expand the agent roster and engagement depth (only after Phase 1–3 are daily-used)

Ordered by risk and by what the next item needs already built, not just by
usefulness — each item is gated on the previous being genuinely useful, not
just built. Anything that goes beyond the current detection-only posture
(docs/AGENTS.md's Pentest Agent finds issues, it doesn't exploit them to
completion) or acts on the local machine rather than a remote target needs
the authorization model extended first — see docs/SECURITY_AND_AUTHORIZATION.md's
new `local-automation` action class and the exploitation-tier note below.
Full agent descriptions: docs/AGENTS.md.

1. **Report Agent** — there needs to be finding volume in Memory first.
2. **Burp Suite integration** — a new Tool Orchestrator stage, same pattern
   as adding nuclei/ffuf/etc. (docs/MVP.md #4): wire Burp's REST API
   (Professional/Enterprise) or CLI scanner into `api/tool_router.py`,
   gated by the same scope check as every other active-scan stage. Lower
   risk than the items below — it's additive to infrastructure that
   already works.
3. **Browser Automation Agent** (Playwright) — login, click, fill forms,
   navigate, capture traffic; the authenticated-testing capability
   docs/VISION.md always described as post-MVP. Gated by the new
   `local-automation` action class (below): it drives a real browser
   session, potentially with real credentials, so it needs its own
   explicit authorization grant, not just an inherited target-scope check.
4. **Bug Hunting Agent** — composes Pentest + Browser (+ Burp) against a
   defined scope. Deferred until items 2-3 exist to compose, since without
   them it's just the Pentest Agent under a different name.
5. **Malware/Document Analysis Sandbox Agent** — opens and detonates
   suspicious files (documents, binaries) to observe behavior. Sandboxed,
   no host network access, full stop — this is the one place "open a
   document" is safe by construction: the document never reaches anything
   real.
6. **Cloud Agent / IAM Agent** — your existing Azure/IAM background makes
   these high-leverage once the core loop is trusted.
7. **SOC Agent**
8. **OSINT Agent** (strictly passive)
9. **Local Automation / Computer-Use Agent** — general desktop control:
   open arbitrary applications/files, drive GUIs beyond a sandboxed browser
   or an isolated malware detonation chamber. Deliberately last: this is
   the highest-risk, most novel capability here, and the one most exposed
   to prompt injection (a malicious page or document tricking the agent
   into taking a real local action). Does not start until the
   `local-automation` action class has a concrete design, not just the
   principle stated below — see "Open decisions to revisit."
10. **Exploitation tier (opt-in, higher risk level)** — today, sqlmap/
    nuclei/dalfox all run at conservative/detection settings
    (`--level=1 --risk=1` etc.) that report a likely issue without
    confirming it via full exploitation. A future opt-in tier could raise
    those levels or add exploit-execution tooling, but only behind a
    strictly stronger authorization than today's self-attestation — e.g.
    require the provable file-token method, never a self-attestation,
    before anything that attempts actual exploitation rather than
    detection.

## Phase 5 — Distribution surfaces (only if this becomes a product)

Desktop app (Tauri), Firefox extension, voice commands, team
collaboration/shared Memory. None of these matter until Phase 1–4 are solid
for a single user.

## Open decisions to revisit

- **Licensing model** — currently proprietary/private (see LICENSE). Revisit
  open-core vs. fully-closed once there's something worth commercializing.
- **"Es" naming** — too short/generic to trademark or search reliably; pick a
  more distinctive product name before any public release (docs/REVIEW.md
  point 7).
- **Team/multi-user Memory** — out of scope until Phase 5; current design
  assumes single-user local Memory.
- **`local-automation` action class design** — docs/SECURITY_AND_AUTHORIZATION.md
  now states the principle (a new action class, gated the same way as
  `passive-recon`/`active-scan`, requiring an explicit session-scoped grant)
  but not the mechanism: what "target" even means for an action that
  controls the local desktop rather than a remote host, how a grant is
  scoped (one task? one session? one specific app?), and how it's revoked.
  Needs a real design pass before Phase 4 item 9 (Local Automation Agent)
  starts, not just the principle.
