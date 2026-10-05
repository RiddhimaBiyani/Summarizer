"""Digestif command line interface (CLI) using Typer."""

import asyncio
import shutil
import sys
from typing import Optional

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
import typer
from rich.console import Console
from rich.table import Table

from digestif.db.repo import db
from digestif.settings import settings

app = typer.Typer(
    name="digestif",
    help="Zero-Cost Personal Content Digest Engine",
    add_completion=False,
)
console = Console()


@app.command()
def doctor() -> None:
    """Checks credentials, database, network reachability, and system tools."""
    console.print("[bold cyan]🔍 Running Digestif System Diagnostics...[/bold cyan]\n")
    table = Table(title="Diagnostic Status")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    # 1. Database & sqlite-vec
    try:
        conn = db.get_connection()
        conn.execute("SELECT count(*) FROM items").fetchone()
        table.add_row(
            "Database & WAL", "[green]OK[/green]", f"SQLite WAL ready at {settings.db_path.name}"
        )
        conn.execute("SELECT count(*) FROM item_vec").fetchone()
        table.add_row("sqlite-vec Extension", "[green]OK[/green]", "Virtual table item_vec loaded")
    except Exception as e:
        table.add_row("Database", "[red]FAIL[/red]", str(e))

    # 2. Telegram Bot
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ALLOWED_USER_ID:
        try:
            resp = httpx.get(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe", timeout=8.0
            )
            if resp.status_code == 200:
                bot_info = resp.json().get("result", {})
                table.add_row(
                    "Telegram Bot", "[green]OK[/green]", f"@{bot_info.get('username')} configured"
                )
            else:
                table.add_row(
                    "Telegram Bot", "[yellow]WARN[/yellow]", f"HTTP {resp.status_code}: {resp.text}"
                )
        except Exception as e:
            table.add_row("Telegram Bot", "[yellow]WARN[/yellow]", f"Unreachable: {e}")
    else:
        table.add_row(
            "Telegram Bot",
            "[yellow]SKIPPED[/yellow]",
            "TELEGRAM_BOT_TOKEN or USER_ID not set in .env",
        )

    # 3. Gmail IMAP & SMTP credentials
    if settings.DIGEST_GMAIL_ADDRESS and settings.DIGEST_GMAIL_APP_PASSWORD:
        table.add_row(
            "Gmail Credentials", "[green]OK[/green]", f"Account: {settings.DIGEST_GMAIL_ADDRESS}"
        )
    else:
        table.add_row(
            "Gmail Credentials",
            "[yellow]SKIPPED[/yellow]",
            "Gmail address or app password unset in .env",
        )

    # 4. LLM API Keys
    if settings.GEMINI_API_KEY:
        table.add_row("Gemini API Key", "[green]OK[/green]", "Google AI Studio key present")
    else:
        table.add_row("Gemini API Key", "[yellow]WARN[/yellow]", "GEMINI_API_KEY unset in .env")

    if settings.GROQ_API_KEY:
        table.add_row("Groq API Key", "[green]OK[/green]", "Groq key present (free tier)")
    else:
        table.add_row("Groq API Key", "[yellow]WARN[/yellow]", "GROQ_API_KEY unset in .env")

    # 5. System Binaries
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        table.add_row("ffmpeg", "[green]OK[/green]", ffmpeg_path)
    else:
        table.add_row(
            "ffmpeg",
            "[yellow]WARN[/yellow]",
            "ffmpeg not found in PATH (needed for audio in Phase 5)",
        )

    console.print(table)
    console.print("\n[dim]Diagnostics complete.[/dim]")


@app.command()
def import_url(
    url: str = typer.Argument(..., help="The URL to import"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Optional user note"),
) -> None:
    """Manually imports a URL into Digestif."""
    from digestif.normalize.dedup import check_and_handle_url_dedup
    from digestif.normalize.detect import detect_source_type
    from digestif.normalize.urls import compute_url_hash, resolve_and_canonicalize

    canonical = asyncio.run(resolve_and_canonicalize(url))
    u_hash = compute_url_hash(canonical)

    existing = check_and_handle_url_dedup(u_hash, new_user_note=note)
    if existing:
        console.print(
            f"[yellow]Item already exists (ID #{existing['id']}); pinned and updated note.[/yellow]"
        )
        return

    source_type = detect_source_type(canonical)
    item_id = db.insert_item(
        source_type=source_type,
        url=url,
        canonical_url=canonical,
        url_hash=u_hash,
        user_note=note,
        status="received",
    )
    db.enqueue_job(kind="extract", item_id=item_id, payload={"url": canonical})
    console.print(
        f"[bold green]Successfully imported URL as Item #{item_id} ({source_type})[/bold green]"
    )


@app.command()
def digest_now(
    budget: Optional[int] = typer.Option(
        None, "--budget", "-b", help="Reading time budget in minutes"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force rebuild even if delivered today"
    ),
) -> None:
    """Builds and delivers the digest immediately."""
    from digestif.digest.builder import build_and_deliver_digest

    console.print("[cyan]Triggering immediate digest build...[/cyan]")
    res = asyncio.run(build_and_deliver_digest(budget_minutes=budget, force=force))
    if res:
        console.print(
            f"[bold green]Digest delivered! ({res.get('word_count')} words, ≈ {res.get('est_minutes')} min)[/bold green]"
        )
    else:
        console.print("[yellow]No items ready for digest.[/yellow]")


@app.command()
def stats() -> None:
    """Displays system metrics, processed items count, and provider usage."""
    conn = db.get_connection()
    items_count = conn.execute("SELECT count(*) as c FROM items").fetchone()["c"]
    ready_count = conn.execute("SELECT count(*) as c FROM items WHERE status = 'ready'").fetchone()[
        "c"
    ]
    digests_count = conn.execute("SELECT count(*) as c FROM digests").fetchone()["c"]
    llm_calls_count = conn.execute("SELECT count(*) as c FROM llm_calls").fetchone()["c"]

    console.print("[bold cyan]📊 Digestif System Metrics[/bold cyan]\n")
    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold green")

    table.add_row("Total Captured Items", str(items_count))
    table.add_row("Ready / Un-digested Items", str(ready_count))
    table.add_row("Total Digests Delivered", str(digests_count))
    table.add_row("Total LLM Calls Recorded", str(llm_calls_count))
    table.add_row("Recurring Cost", "₹0.00")

    console.print(table)


@app.command()
def run() -> None:
    """Starts all Digestif services: Telegram poller, IMAP poller, worker pool, and scheduler."""
    console.print("[bold green]Starting Digestif Service (all-in-one)...[/bold green]")
    asyncio.run(_run_all())


async def _run_all() -> None:
    from digestif.capture.telegram import telegram_poller
    from digestif.jobs.queue import worker_pool
    from digestif.jobs.scheduler import scheduler_service
    from digestif.reliability.catchup import check_and_run_catchup

    # 1. Start worker pool
    await worker_pool.start()
    # 2. Start scheduler
    await scheduler_service.start()
    # 3. Run initial catch-up check on wake
    await check_and_run_catchup()
    # 4. Start Telegram bot long polling (runs indefinitely)
    try:
        await telegram_poller.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await scheduler_service.stop()
        await worker_pool.stop()
        console.print("[yellow]Digestif service stopped.[/yellow]")


if __name__ == "__main__":
    app()
