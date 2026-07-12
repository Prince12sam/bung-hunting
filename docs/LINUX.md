# Running on Linux

Everything in docs/GETTING_STARTED.md applies — this doc covers only what's
different on Linux, and is honest about what's actually been verified
there versus what's inferred from reading the code.

**Status: not yet run on a real Linux box.** Everything below reflects (a)
grepping the codebase for platform-specific assumptions (there are almost
none — see the list at the bottom) and (b) how Docker networking actually
differs on native Linux vs. Docker Desktop. Treat this as a well-reasoned
starting point, not a "confirmed working" claim — if you try it, tell us
what broke.

## What's actually easier on Linux

Docker is native here — no Hyper-V/WSL2 backend, no virtualization/BIOS
prerequisites, no "Docker Desktop won't start" saga (see docs/REVIEW.md's
history of exactly that fight on Windows). `docker run` talks directly to
the daemon on the same kernel. Every containerized tool (semgrep, httpx,
subfinder, katana, nmap, nuclei, ffuf, dalfox, sqlmap) should work
identically, since none of them are Windows-specific — semgrep is
containerized here for consistency and sandboxing (docs/SECURITY_AND_AUTHORIZATION.md),
not because Linux needs it that way.

## Setup differences

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .        # registers the `es` command

cp .env.example .env
cd docker && cp .env.example .env && docker compose up -d && cd ..
docker build -t es/ffuf:local docker/tools/ffuf
```

Same steps as Windows otherwise — `python3`/`pip3` if your distro doesn't
symlink `python`/`pip` to the Python 3 versions (many minimal/server
distros don't).

## The one real behavioral difference: `ES_CONTAINER_HOST_ALIAS`

Scanning `localhost` (or any RFC1918 address the Agent Core itself can
reach) means a container needs to reach back out to the host machine.
Docker Desktop (Windows/Mac) exposes the host at the special DNS name
`host.docker.internal` automatically — that's `api/config.py`'s default for
`container_host_alias`. **Native Linux Docker does not resolve that name by
default.**

Fix: point it at the `docker0` bridge gateway IP instead, which containers
*can* reach directly on Linux:

```bash
ip addr show docker0 | grep 'inet '   # commonly 172.17.0.1
```

Then in `.env`:

```
ES_CONTAINER_HOST_ALIAS=172.17.0.1
```

This only matters for scanning your own machine's services. Scanning a
real remote domain (`es scan some-real-target.com`) never goes through
this path — the container reaches the internet directly, same as any OS.

## Already fixed for Linux (found via testing on Windows, but the fix is cross-platform)

- `run_tests` (used by `fix --apply`) used to hardcode the literal string
  `"python"` — many Linux distros only ship `python3` on PATH. Now uses
  `sys.executable`, which is also strictly more correct on Windows (same
  interpreter/venv Es itself runs in, not whatever "python" resolves to).
- Every `subprocess.run` call decodes tool output as UTF-8 explicitly
  rather than relying on the platform's default locale encoding — this was
  a real Windows-specific bug (cp1252 crashing on real page content), not a
  Linux one, but the fix applies everywhere.

## What to actually check if you try this

1. `docker run --rm hello-world` works and is fast (confirms the daemon
   itself is healthy before blaming Es for anything).
2. `es scan localhost` after setting `ES_CONTAINER_HOST_ALIAS` per above —
   should find open ports the same way the Windows walkthrough did.
3. Give Docker real memory if it's constrained (cgroup limits, a container,
   a small VM) — see the note in docs/GETTING_STARTED.md's Notes section;
   this bit hard on Windows and there's no reason to assume Linux is immune
   if the daemon itself is resource-starved.
