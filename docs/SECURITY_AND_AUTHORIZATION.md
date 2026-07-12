# Security & Authorization Model

Es runs active security tooling (nmap, sqlmap, ffuf, nuclei active
templates, authenticated Playwright automation). This doc is the gate that
every one of those tools must pass through before it fires. Read this before
writing any code that calls the Tool Orchestrator or the Pentest/Browser
agents' active paths.

## Core rule

**A conversational "may I?" is not authorization.** An LLM asking the user
"do you want me to enumerate the GraphQL schema?" and getting a "yes" in
chat is a UX confirmation, not a control — it doesn't stop a
misconfigured run, a prompt-injected page, or a scripted/non-interactive
invocation from firing anyway. Authorization must be a technical check the
Tool Router performs, independent of what the LLM decided to say.

This is not the same thing as self-attestation (verification method 3
below) being an interactive CLI prompt. The distinction: the prompt isn't
the LLM inferring consent from a chat exchange it's free to interpret —
it's `api.scope.require_authorized` refusing to run *anything*, in code,
until a specific Target row says `verified`, and self-attestation is one
explicit, human-typed, logged way to set that row (the weakest one — see
below). A page telling the agent "the user already agreed to this" or an
LLM deciding a prior message implied approval does not touch this table
and changes nothing.

## Scope model

Every target (domain, IP range, repo) has a **scope record** in Memory with:

- `status`: `unverified` | `verified` | `revoked`
- `verification_method`: how ownership/authorization was established
- `authorized_actions`: which action classes are allowed (passive-recon,
  active-scan, exploit, local-automation — see below for the last one)
- `expires_at`: scope records expire; stale authorization is treated as none

### Verification methods (any one required to move a target to `verified`)

1. **File token** — place an Es-issued token at
   `https://target/.well-known/es-auth.txt`, same pattern as Google
   Search Console / Burp Suite Enterprise domain verification. Implemented:
   `api.scope.verify_file_token` / `es verify-target`.
2. **DNS TXT record** — `_es-auth.target` TXT record matching an
   issued token. Not implemented yet — file-token covers the same proof
   today.
3. **Self-attestation** — the user explicitly states, in an action distinct
   from a default/ambient "yes" (a dedicated CLI prompt requiring a typed
   statement, or `--self-attest "<statement>"`), that they own or are
   authorized to test the target. Implemented:
   `api.scope.verify_self_attestation` / `es scan`'s interactive prompt.
   This is the weakest method by design:
   - The statement text itself is stored in `verification_method`, so a
     false attestation is attributable in any later report, unlike an
     unlogged chat "sure, go ahead".
   - TTL is short (`ES_SELF_ATTEST_TTL_DAYS`, default 1 day) — far shorter
     than file-token's 30 — to bound how long a false or stale attestation
     stays usable.
   - Still gated behind an explicit action, not inferred from conversation:
     the CLI requires either a real terminal confirmation *and* a typed
     reason, or an explicit `--self-attest` flag for scripting. An LLM
     deciding on its own that "the user probably meant yes" does not
     satisfy this.
4. **Local/private ranges the user's own machine can reach** (RFC1918,
   localhost, explicitly declared lab CIDRs) — treated as pre-verified for
   personal lab use, since there's no third party to harm. Implemented:
   `api.scope._is_private_or_local`.

### What the gate blocks

- Any `active-scan`, `exploit`, or `local-automation` class action against
  a target that is `unverified` or `revoked`, regardless of what the
  agent's plan says.
- Any action against a target once `expires_at` has passed, until
  re-verified.
- Silent scope expansion — if recon discovers a new subdomain/host, it
  enters as `unverified` and does not inherit the parent domain's scope
  automatically.

### What the gate does not block

- Passive/read-only checks (headers, robots.txt, sitemap.xml, public JS
  parsing, WAF fingerprinting) — these are equivalent to a browser page load
  and carry no additional risk.

## The `local-automation` action class (principle stated, not yet built)

docs/ROADMAP.md Phase 4 plans a Browser Automation Agent (Playwright:
login, click, navigate, capture traffic) and a Local Automation /
Computer-Use Agent (opening applications/files, driving GUIs beyond a
sandboxed browser or malware-detonation chamber). Both are a different
shape of risk than scanning a remote target: they act *on the local
machine or a real authenticated session*, and both are exactly the kind
of capability a prompt-injected page or a malicious document could try to
turn against the user directly.

The principle, decided now so it isn't improvised later under
implementation pressure: **the same gate, not a special case.**

- Extend the existing `require_authorized` mechanism with a
  `local-automation` action class rather than inventing a parallel,
  weaker check "because it's local." Local isn't automatically safe —
  it's the user's own session, files, and desktop, which is arguably
  higher-stakes than an isolated remote scan, not lower.
- No default-on. An agent deciding a task "probably needs" browser or
  desktop control is exactly the conversational-approval failure mode the
  Core rule above already rules out — this needs its own explicit grant,
  the same way `es scan` needs a verified Target row before nmap runs.
- Sandboxing still applies underneath the gate, not instead of it: the
  Malware/Document Sandbox Agent's "no host network access, full stop"
  rule (below) is what makes documents genuinely safe to open, independent
  of whether the authorization step is also correct. Authorization and
  isolation are both required, neither substitutes for the other.

**Not yet decided** (tracked in docs/ROADMAP.md's open decisions, needed
before Phase 4 item 9 starts): what "target" means for an action that
isn't a remote host — a URL for authenticated browsing fits the existing
Target model fine, but "open this local file" or "launch this
application" doesn't obviously reduce to a domain/IP. Likely shape: a
grant scoped to a specific task or session rather than a persistent Target
row, but that's a real design exercise, not a one-line addition.

## Secrets and data egress

- Anything the Browser Agent or Pentest Agent finds that matches a
  credential/key/token pattern (AWS/Azure/GCP keys, Stripe/Paystack keys,
  JWTs, Firebase/Supabase service keys, generic high-entropy secrets) is
  tagged `sensitive` at the point of discovery.
- `sensitive`-tagged content is redacted before it is included in any prompt
  sent to a cloud LLM. Summarization/explanation of a finding that contains a
  secret happens on a local model, or on a redacted copy.
- Secret *values* are never embedded into pgvector. Memory stores a reference
  (location, type, hash) — the value itself lives in a local encrypted vault
  (e.g. OS keychain or an encrypted-at-rest table with a key not stored in
  the same database).
- Full audit log of every tool invocation: target, action class, scope
  status at time of execution, who/what initiated it. This is what makes the
  eventual Report Agent's evidence trail credible.

## Sandboxing

- Subprocess/container isolation for every external tool the Tool
  Orchestrator runs — no active tool runs with the same privileges as the
  Agent Core process.
- Malware/Document Analysis Sandbox Agent (post-MVP) gets no network access
  to the host machine, full stop — samples and suspicious documents are
  detonated/opened in an isolated sandbox only, never on the real
  filesystem or a real application. This is what makes "open a document"
  safe by construction for that one agent; it is not a general license for
  other agents to open arbitrary files outside a sandbox.
- The Local Automation / Computer-Use Agent (docs/ROADMAP.md Phase 4 item
  9) has no such blanket isolation available to it by definition — driving
  a real desktop means touching real applications and real files. That's
  exactly why it's gated by its own `local-automation` authorization grant
  above, rather than assumed safe because it runs locally.

## Legal

This platform is for authorized security testing only: engagements you're
contracted for, programs you're enrolled in, or systems you own. The scope
gate above is the technical enforcement of that; it does not replace having
an actual signed engagement or program scope in hand before testing anything
that isn't your own infrastructure.
