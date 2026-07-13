# Running on Windows

Everything in docs/GETTING_STARTED.md applies — this doc covers what's
different (and what actually went wrong, and how it got fixed) on Windows.
This is where the project was originally built, so it's the most heavily
tested platform.

**Status: fully verified.** `analyze`, `fix`, `scan` (including full
8-tool runs against real live sites), `es serve`/`stop`/`status`, and both
cloud and local (Ollama) LLM backends have all been run for real here.

## Prerequisites — the part that actually caused problems

Docker Desktop needs a working WSL2 or Hyper-V backend, and getting there
had three separate real failure points, in order:

1. **Hardware virtualization (Intel VT-x / AMD-V) disabled in firmware.**
   Blocks WSL2 and Hyper-V equally. Fix: reboot into BIOS/UEFI (Del/F2/F10/F12
   depending on the board), enable it under Advanced/CPU Configuration,
   save & exit. `systeminfo`'s "Hyper-V Requirements" section will show all
   four checks as "Yes" once this is right.
2. **WSL/VirtualMachinePlatform Windows features not enabled**, even with
   virtualization on. Needs an elevated (Administrator) prompt:
   ```powershell
   dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   ```
   Then reboot — these only take effect after a restart.
3. **WSL2 itself still failed to create a VM** even after both of the
   above, for reasons that weren't fully resolved. Switching Docker Desktop
   to the **Hyper-V backend** instead (Settings → General → uncheck "Use
   the WSL 2 based engine" → Apply & Restart) is what actually worked.

If Docker Desktop is already running fine for you, none of this applies —
it's here because getting from zero to a working Docker Desktop was
genuinely not a one-step process.

## Give Docker real memory

Docker Desktop's default resource allocation (as low as ~2GB RAM for its
VM) caused real, reproducible multi-minute to hour-long hangs once
several tools (nuclei, dalfox, sqlmap) ran back-to-back against a real
site — not a code bug, the containers themselves were starved. Settings →
Resources → Memory, raise to 6-8GB or more if you have it. Confirmed fix:
the exact same test suite that took 45+ minutes and failed under low
memory ran clean in under 5 minutes after raising it.

## `ES_CONTAINER_HOST_ALIAS` — no action needed

Docker Desktop exposes the host machine at `host.docker.internal`
automatically, which is `api/config.py`'s default. Scanning `localhost`
just works without touching `.env` — this is the one thing that's
*easier* on Windows/Mac than native Linux (docs/WINDOWS.md's counterpart,
docs/LINUX.md, needs the `docker0` gateway IP instead).

## Bugs found here that affect every platform, not just Windows

All fixed, but worth knowing about since they were found through real use,
not code review:

- **litellm's `timeout=` isn't reliably enforced for every provider.** A
  local Ollama "thinking"/reasoning model ran 30+ minutes past a 60s
  timeout, blocking an entire scan request. Every LLM call is now wrapped
  in its own hard wall-clock deadline in Python (`api/llm_router.py`),
  independent of whatever litellm does internally.
- **Killing a `docker run` client process does not stop the container.**
  A tool that outlived its timeout kept running server-side indefinitely,
  still hitting the real target, because nothing told Docker to stop it.
  Every container now gets an explicit `--name` so a timeout can actually
  `docker kill` it — and that cleanup call itself is bounded to 15s so it
  can never become a second hang.
- **`subprocess.run(..., text=True)` decodes using the platform's default
  locale encoding** (cp1252 on this machine), not UTF-8. Real page content
  from a live site routinely contains bytes cp1252 can't decode, crashing
  a background reader thread with a `UnicodeDecodeError` that doesn't look
  like a normal exception. Every subprocess call now decodes as UTF-8
  explicitly with `errors="replace"`.
- **Typer 0.15.1's rich help formatter breaks under Click ≥ 8.2** —
  `es --help` threw `TypeError: Parameter.make_metavar() missing 1
  required positional argument: 'ctx'`. Pinned `click<8.2` in
  requirements.txt. Actual commands worked fine even with the broken
  Click version; only `--help`'s rendering was affected.
- **A single-threaded test HTTP server couldn't keep up with ffuf's ~40
  concurrent connections**, making a test fixture look randomly broken
  when the real tool integration (proven against a live production site)
  was fine. Test-only issue, but worth knowing this class of bug exists if
  you write your own fixtures against these tools.

## What to check if something seems wrong

1. `systeminfo | findstr /C:"Hyper-V Requirements" /A:5` (or just open
   Docker Desktop — it will complain loudly if its backend isn't healthy).
2. `docker run --rm hello-world` — fast and clean confirms the daemon
   itself is fine before blaming Es for anything.
3. `es status` — confirms the Agent Core specifically, separate from Docker.
4. If things get erratic (slow, timing out) after hours of heavy use in
   one session, a plain Docker Desktop restart resolved it every time this
   came up — try that before deep debugging.
