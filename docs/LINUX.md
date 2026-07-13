# Running on Linux

Everything in docs/GETTING_STARTED.md applies — this doc covers only what's
different on Linux.

**Status: verified on Kali Linux.** `analyze`, `scan`, the `scorpion` console
command, `scorpion serve`/`stop`/`status`, and Ollama-backed summaries have
all been run for real, including two live scans against real domains with
real findings persisted. What follows reflects that testing, not just a
reading of the code.

## What's actually easier on Linux

Docker is native here — no Hyper-V/WSL2 backend, no virtualization/BIOS
prerequisites, no "Docker Desktop won't start" fight. `docker run` talks
directly to the daemon on the same kernel. Every containerized tool
(semgrep, httpx, subfinder, katana, nmap, nuclei, ffuf, dalfox, sqlmap)
works the same way, since none of them are Windows-specific — semgrep is
containerized for consistency/sandboxing, not because Linux needs it.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .        # registers the `scorpion` command

cp .env.example .env
cd docker && cp .env.example .env && docker compose up -d && cd ..
docker build -t scorpion/ffuf:local docker/tools/ffuf
```

Same steps as Windows otherwise — `python3`/`pip3` if your distro doesn't
symlink `python`/`pip` to the Python 3 versions (many minimal/server
distros don't).

## The one real behavioral difference: `SCORPION_CONTAINER_HOST_ALIAS`

Scanning `localhost` (or any RFC1918 address the Agent Core itself can
reach) means a container needs to reach back out to the host machine.
Docker Desktop (Windows/Mac) exposes the host at the special DNS name
`host.docker.internal` automatically — native Linux Docker does not
resolve that name by default.

Fix: point it at the `docker0` bridge gateway IP instead:

```bash
ip addr show docker0 | grep 'inet '   # commonly 172.17.0.1
```

Then in `.env`:

```
SCORPION_CONTAINER_HOST_ALIAS=172.17.0.1
```

Confirmed working exactly as expected on Kali — `172.17.0.1` was the
gateway, set it, `scorpion scan localhost` reached the host correctly.

This only matters for scanning your own machine's services. Scanning a
real remote domain never goes through this path — the container reaches
the internet directly, same as any OS.

## Already fixed for Linux (found via testing on Windows, but the fix is cross-platform)

- `run_tests` (used by `fix --apply`) used to hardcode the literal string
  `"python"` — many Linux distros only ship `python3` on PATH. Now uses
  `sys.executable`.
- Every `subprocess.run` call decodes tool output as UTF-8 explicitly
  rather than relying on the platform's default locale encoding.
- LLM calls are bounded by a hard wall-clock timeout in Python, not just
  litellm's own `timeout=` kwarg (confirmed unreliable for at least the
  Ollama provider) — a slow/CPU-bound local model can no longer hang a
  whole request indefinitely.

## Things that actually happened testing this on Kali

- A `git clone` + `pip install -r requirements.txt` + `pip install -e .`
  worked cleanly on the first try — no Linux-specific dependency issues.
- Docker was already installed and the daemon already running (Kali
  ships it, but don't assume every distro does).
- Ollama models already pulled locally worked fine as `ollama/<name>` —
  including ones with a namespace prefix in their name (e.g.
  `ollama/huihui_ai/qwen3.5-abliterated:9b`), litellm handles the extra
  slash correctly.
- Ctrl+C in a terminal signals the whole foreground process group, not
  just the process you meant to stop — this killed a manually-backgrounded
  Agent Core mid-session before `scorpion serve` existed. `scorpion serve`
  now detaches properly (`start_new_session=True`) specifically so this
  can't happen again.
- A large local "thinking"/reasoning model running CPU-only can take much
  longer to answer than a small direct-answer model — `ollama ps` shows
  what's actually loaded and generating if a request seems slow. Pick a
  small non-reasoning model (e.g. `llama3.2`) for interactive use.

## What to check if something seems wrong

1. `docker run --rm hello-world` works and is fast (confirms the daemon
   itself is healthy before blaming Scorpion for anything).
2. `scorpion status` — is the Agent Core actually running, and healthy?
3. Give Docker real memory if it's constrained (cgroup limits, a small VM)
   — this caused genuine multi-minute to hour-long hangs on Windows when
   under-provisioned; there's no reason to assume Linux is immune if the
   daemon itself is resource-starved.
