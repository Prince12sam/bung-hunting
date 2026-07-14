import threading

import httpx
import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from cli import launch as launch_lifecycle, server as server_lifecycle
from cli.client import BASE_URL, SCAN_TIMEOUT, get as http_get, post

app = typer.Typer(add_completion=False, help="Scorpion v2 — local AI security platform CLI")
console = Console()

# Plain ASCII only (no box-drawing/emoji) — a real UnicodeEncodeError on
# Windows' legacy cp1252 console is what killed the earlier checkmark/cross
# symbols elsewhere in this CLI, and a banner is the last place we want a
# crash before the tool has even started.
BANNER = r"""
  _____  _____ ____  _____  _____ _____ ____  _   _
 / ____|/ ____/ __ \|  __ \|  __ \_   _/ __ \| \ | |
| (___ | |   | |  | | |__) | |__) || || |  | |  \| |
 \___ \| |   | |  | |  _  /|  ___/ | || |  | | . ` |
 ____) | |___| |__| | | \ \| |    _| || |__| | |\  |
|_____/ \_____\____/|_|  \_\_|   |_____\____/|_| \_|
                   v2 -- local AI security platform
"""


def _connection_error_hint() -> None:
    console.print(
        f"[red]Could not reach the Scorpion Agent Core at {BASE_URL}.[/red]\n"
        "Start it: [bold]scorpion serve[/bold]"
    )


@app.command()
def launch() -> None:
    """Start everything: checks Docker, brings up Postgres, builds the ffuf
    image if missing, then starts the Agent Core. Safe to re-run — every
    step is idempotent. This is the one command to run each time you sit
    down to use Scorpion."""
    console.print(f"[bold red]{BANNER}[/bold red]")
    for ok, message in launch_lifecycle.launch():
        console.print(f"[green]OK  {message}[/green]" if ok else f"[red]FAIL {message}[/red]")
        if not ok:
            raise typer.Exit(1)


@app.command()
def serve(
    foreground: bool = typer.Option(
        False, "--foreground", help="Run attached to this terminal instead of detached in the background"
    ),
) -> None:
    """Start the Agent Core. Detached and tracked by PID file unless --foreground."""
    if foreground:
        server_lifecycle.start(foreground=True)
        return
    ok, message = server_lifecycle.start()
    console.print(f"[green]{message}[/green]" if ok else f"[yellow]{message}[/yellow]")


@app.command()
def stop() -> None:
    """Stop a background Agent Core started with `scorpion serve`."""
    ok, message = server_lifecycle.stop()
    console.print(f"[green]{message}[/green]" if ok else f"[yellow]{message}[/yellow]")


@app.command()
def status() -> None:
    """Check whether the Agent Core is running."""
    console.print(server_lifecycle.status())


@app.command()
def analyze(path: str = typer.Argument(..., help="Local path to analyze")) -> None:
    """Static security review of local code (Coding Agent, no network activity)."""
    try:
        result = post("/v1/analyze", {"path": path})
    except httpx.ConnectError:
        _connection_error_hint()
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Agent Core error: {exc.response.text}[/red]")
        raise typer.Exit(1)

    if result.get("error"):
        console.print(f"[yellow]Warning: {result['error']}[/yellow]")

    findings = result["findings"]
    if not findings:
        console.print("[green]No findings.[/green]")
    else:
        table = Table(title=f"{len(findings)} finding(s)")
        table.add_column("Severity")
        table.add_column("Rule")
        table.add_column("Location")
        table.add_column("Description")
        for f in findings:
            loc = f"{f['file_path']}:{f['line']}" if f.get("file_path") else "-"
            table.add_row(f["severity"], f["title"], loc, f["description"][:80])
        console.print(table)

    console.print("\n[bold]Summary[/bold]")
    console.print(result["summary"])


@app.command()
def fix(
    path: str = typer.Argument(..., help="Local path (git repo) to fix"),
    apply: bool = typer.Option(False, "--apply", help="Write the proposed patch to disk and run tests"),
    commit: bool = typer.Option(False, "--commit", help="Commit if tests pass after --apply. Ignored without --apply."),
) -> None:
    """Find issues and propose a patch (Coding Agent). Nothing touches disk without --apply."""
    try:
        proposal = post("/v1/fix/propose", {"path": path})
    except httpx.ConnectError:
        _connection_error_hint()
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Agent Core error: {exc.response.text}[/red]")
        raise typer.Exit(1)

    if proposal.get("error"):
        console.print(f"[red]{proposal['error']}[/red]")
        raise typer.Exit(1)

    if not proposal["diff"]:
        console.print("[green]No findings, nothing to patch.[/green]")
        return

    console.print("[bold]Proposed patch[/bold]")
    console.print(proposal["diff"])

    if not apply:
        console.print("\n[dim]Re-run with --apply to write this to disk and run tests.[/dim]")
        return

    apply_result = post("/v1/fix/apply", {"path": path, "diff": proposal["diff"], "commit": commit})
    if apply_result.get("error"):
        console.print(f"[yellow]{apply_result['error']}[/yellow]")
    console.print(f"Applied: {apply_result['applied']}  Committed: {apply_result['committed']}")
    console.print(apply_result["test_output"])


@app.command()
def scan(
    target: str = typer.Argument(..., help="Domain/IP/host to scan"),
    self_attest: str = typer.Option(
        None,
        "--self-attest",
        help="Non-interactively attest ownership/authorization with this statement "
        "(skips the prompt below; still the weakest, logged verification method)",
    ),
) -> None:
    """Orchestrator-driven recon + active scan chain (Pentest Agent).

    Active stages only run against targets verified in scope.
    `localhost`/private IPs auto-verify. Anything else prompts for
    self-attestation (weak, logged) or use `scorpion verify-target` first
    for a real, provable verification.
    """
    try:
        status = post("/v1/targets/status", {"target": target})
    except httpx.ConnectError:
        _connection_error_hint()
        raise typer.Exit(1)

    if status["status"] != "verified":
        statement = self_attest
        if not statement:
            console.print(
                f"[yellow]Target '{target}' isn't verified — no one has technically proven "
                "control over it.[/yellow]"
            )
            if not typer.confirm(
                f"Do you personally attest that you own or are explicitly authorized to test "
                f"'{target}'? This is logged against the target, not a blanket approval."
            ):
                console.print(
                    "Not scanning. For a stronger, provable verification instead, use "
                    "[bold]scorpion verify-target[/bold] (file-token method)."
                )
                raise typer.Exit(1)
            statement = typer.prompt(
                'Briefly state your authorization (e.g. "I own this domain", "bug bounty program X")'
            )

        attest = post("/v1/targets/self-attest", {"target": target, "statement": statement})
        console.print(f"[dim]Recorded: {attest['verification_method']}[/dim]")

    console.print(
        "[dim]Running the full pipeline — against a real site this can take several "
        "minutes (nuclei alone can run ~3000 requests). Live stage progress below.[/dim]"
    )

    outcome: dict = {}

    def _run_scan() -> None:
        try:
            outcome["result"] = post("/v1/scan", {"target": target}, timeout=SCAN_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - re-raised on the main thread below
            outcome["error"] = exc

    worker = threading.Thread(target=_run_scan, daemon=True)
    worker.start()

    with Live(console=console, refresh_per_second=2, transient=True) as live:
        while worker.is_alive():
            try:
                progress = http_get("/v1/scan/progress", params={"target": target})
            except Exception:  # noqa: BLE001 - progress polling is best-effort, never fatal
                progress = {"running": False}

            if progress.get("running"):
                live.update(
                    f"[cyan]Running: {progress['stage']}[/cyan] "
                    f"(stage {progress['stage_index']}/{progress['stage_total']}, "
                    f"{progress['elapsed_seconds']:.0f}s elapsed)"
                )
            else:
                live.update("[dim]Starting…[/dim]")
            worker.join(timeout=1)

    if "error" in outcome:
        exc = outcome["error"]
        if isinstance(exc, httpx.ConnectError):
            _connection_error_hint()
            raise typer.Exit(1)
        if isinstance(exc, httpx.ReadTimeout):
            console.print(
                f"[red]No response after {SCAN_TIMEOUT}s.[/red] The scan may still be running "
                "server-side — the Agent Core doesn't cancel work just because the CLI stopped "
                "waiting. Check its findings later rather than re-running immediately."
            )
            raise typer.Exit(1)
        if isinstance(exc, httpx.HTTPStatusError):
            console.print(f"[red]Agent Core error: {exc.response.text}[/red]")
            raise typer.Exit(1)
        raise exc

    result = outcome["result"]

    for w in result["warnings"]:
        console.print(f"[yellow]{w}[/yellow]")

    findings = result["findings"]
    if not findings:
        console.print("[green]No findings.[/green]")
    else:
        table = Table(title=f"{len(findings)} finding(s)")
        table.add_column("Tool")
        table.add_column("Severity")
        table.add_column("Title")
        table.add_column("Description")
        for f in findings:
            table.add_row(f["source_tool"], f["severity"], f["title"], f["description"][:80])
        console.print(table)

    console.print("\n[bold]Summary[/bold]")
    console.print(result["summary"])


@app.command("verify-target")
def verify_target(
    target: str = typer.Argument(..., help="Domain/host to verify"),
    token: str = typer.Option(..., "--token", help="Token placed at https://<target>/.well-known/scorpion-auth.txt"),
) -> None:
    """Verify scope authorization via the file-token method before scanning a target you don't own."""
    try:
        result = post("/v1/targets/verify", {"target": target, "token": token})
    except httpx.ConnectError:
        _connection_error_hint()
        raise typer.Exit(1)

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{target} is now {result['status']} ({result['verification_method']})[/green]")


if __name__ == "__main__":
    app()
