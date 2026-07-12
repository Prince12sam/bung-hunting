# Getting Started

Phase 1 (Agent Core + Memory + CLI: `analyze` / `fix`) and Phase 2 (Tool
Orchestrator: `scan` with httpx, subfinder, katana, nmap, nuclei, ffuf,
dalfox, sqlmap) are both done — see docs/MVP.md for exact status.

Written and verified on Windows; see docs/LINUX.md for what's different
(and what's still unverified) running this on Linux.

## Prerequisites

- Python 3.11+
- Docker running — every external security tool (including semgrep, which
  has no native Windows build) runs sandboxed in a container. On Windows/Mac
  that's Docker Desktop; on Linux, the native Docker daemon (see
  docs/LINUX.md — no Docker Desktop needed, and fewer quirks than Windows)

## Setup

```
python -m venv .venv

.venv\Scripts\activate           # Windows
source .venv/bin/activate        # Linux/Mac

pip install -r requirements.txt
pip install -e .                 # registers the `es` command (pyproject.toml)

cp .env.example .env             # then fill in ES_CODING_MODELS + a provider key
                                  # (optional — analyze/fix work without one,
                                  # just without LLM summaries/patches)

cd docker
cp .env.example .env              # set a real ES_PG_PASSWORD — compose refuses to start without one
docker compose up -d              # starts Postgres+pgvector on localhost:55432
cd ..

# ffuf has no maintained official Docker image — build it once from source:
docker build -t es/ffuf:local docker/tools/ffuf
```

## Run the Agent Core

```
uvicorn api.main:app --host 127.0.0.1 --port 8731
```

On startup it creates the `vector` extension and all tables if they don't
exist yet (fine for MVP; a real migration tool comes once the schema
stabilizes — see docs/ROADMAP.md).

## Use the CLI

Either `es <command>` (after `pip install -e .`) or `python -m cli.main
<command>` — identical, the installed command is just a shortcut.

```
es analyze path/to/code
es fix path/to/repo              # proposes a patch, doesn't touch disk
es fix path/to/repo --apply       # writes the patch, runs pytest
es fix path/to/repo --apply --commit   # + commits if tests pass

es scan localhost                # local/private targets auto-verify, scans immediately
es scan some-target.example       # prompts for self-attestation (see below)
es verify-target some-target.example --token <token>   # stronger, provable verification
```

## Scanning a target you don't own

`scan` runs the full Tool Orchestrator pipeline (docs/MVP.md #4) — but only
against targets the scope gate has verified (docs/SECURITY_AND_AUTHORIZATION.md).
`localhost` and RFC1918 addresses auto-verify since there's no third party
to harm. For anything else, `scan` gives you two paths:

- **Self-attestation (quick, weaker)** — `scan` prompts you interactively:
  confirm you own/are authorized to test the target, then type a short
  statement of that authorization. Both are logged against the target (a
  false attestation is attributable later, unlike an unlogged chat "yes")
  and the verification expires after 1 day by default
  (`ES_SELF_ATTEST_TTL_DAYS`) — short on purpose, since there's no
  technical proof behind it. For scripting, skip the prompt with
  `scan <target> --self-attest "reason"`.
- **File-token (slower, provable)** — pick any token string, place it at
  `https://<target>/.well-known/es-auth.txt` on the target itself (proving
  you control it), then run `verify-target <target> --token <same
  string>`. Verification lasts 30 days (`ES_SCOPE_VERIFICATION_TTL_DAYS`).

Either way, an unverified target isn't scanned — the CLI reports it as
skipped, per stage, until one of the above succeeds. Active-scan tools
(nmap, nuclei, ffuf, dalfox, sqlmap) send real requests/payloads — only
authorize something you're actually allowed to test.

## Without an LLM key configured

`analyze` still runs semgrep and returns raw findings; the summary field
explains that no LLM is configured instead of a real summary. `fix` requires
an LLM (semgrep alone doesn't write patches) and will return a clear error
if none is configured.

## Notes

- `fix --apply` assumes `path` is a git repository (uses `git apply` / `git
  commit`). Commit is opt-in and only happens if `pytest` passes after the
  patch is applied — see docs/REVIEW.md point 6.
- Findings are persisted to Memory (Postgres) keyed by project name. If
  Postgres isn't reachable, `analyze`/`fix` still work — you just won't get
  cross-session recall of past findings.
- **Give Docker at least ~6-8GB of RAM.** Found this the hard way: with
  Docker Desktop's default ~2GB, `scan`'s later stages (nuclei, dalfox,
  sqlmap running back to back against a real site) got erratic multi-minute
  to hour-long hangs under memory pressure — not a code bug, the containers
  themselves were starved. Docker Desktop: Settings → Resources → Memory.
  Native Linux Docker isn't capped the same way by default, but the same
  tools still need real memory to run several at once without contention.
- A `scan` against a real, content-heavy site can legitimately take several
  minutes end-to-end (nuclei alone can run ~3000 requests) — the CLI waits
  up to 30 minutes for it. If you scan the same real site again immediately
  after, expect thinner results: many sites start rate-limiting/blocking
  after an intensive first pass, which is the target defending itself, not
  a bug here.
