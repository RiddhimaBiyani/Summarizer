"""Telegram bot command handlers for /today, /digest, /budget, /time, /help."""

import re

import yaml

from digestif.db.repo import db
from digestif.settings import settings


async def handle_telegram_command(command_text: str) -> str:
    """Parses and executes a slash command received from the user."""
    parts = command_text.strip().split()
    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    if cmd == "/today":
        return _handle_today()
    elif cmd == "/digest":
        return await _handle_digest(args)
    elif cmd == "/budget":
        return _handle_budget(args)
    elif cmd == "/time":
        return _handle_time(args)
    elif cmd in ("/help", "/start"):
        return _handle_help()
    else:
        return f"Unknown command '{cmd}'. Send /help to see all available commands."


def _handle_today() -> str:
    items = db.list_today_items()
    if not items:
        return "📭 No items saved today yet. Share links, emails, or notes to get started!"

    lines = [f"📚 <b>Today's Saved Items ({len(items)}):</b>\n"]
    status_emojis = {
        "received": "📥",
        "extracting": "⚙️",
        "extracted": "📄",
        "analyzing": "🧠",
        "analyzed": "🔍",
        "ready": "✅",
        "failed": "❌",
        "needs_user": "🤔",
    }

    for idx, it in enumerate(items, 1):
        st = it.get("status", "received")
        emoji = status_emojis.get(st, "📌")
        title = it.get("title") or it.get("url") or f"Item #{it['id']}"
        orig_min = it.get("original_minutes") or 0.0
        lines.append(f"{idx}. {emoji} <b>{title[:50]}</b> (≈{orig_min}m) — <i>{st}</i>")

    return "\n".join(lines)


async def _handle_digest(args: list[str]) -> str:
    budget_minutes = None
    if args and args[0].isdigit():
        budget_minutes = int(args[0])

    from digestif.digest.builder import build_and_deliver_digest

    result = await build_and_deliver_digest(budget_minutes=budget_minutes, force=True)
    if not result:
        return "⚠️ No ready items found to build tonight's digest. Save a link first!"

    est = result.get("est_minutes", 0.0)
    return f"🚀 Digest built and delivered! Estimated read time: {est} min."


def _handle_budget(args: list[str]) -> str:
    if not args:
        current = settings.app_config.get("digest", {}).get("default_budget_minutes", 20)
        return f"Current reading budget is {current} minutes. Change with: /budget 15, 20, or 30."

    val = args[0].lower()
    if val not in ("15", "20", "30", "auto"):
        return "Invalid budget. Please choose: 15, 20, 30, or auto."

    # Update config.yaml
    cfg_file = settings.BASE_DIR / "config" / "config.yaml"
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if "digest" not in cfg:
            cfg["digest"] = {}
        cfg["digest"]["default_budget_minutes"] = int(val) if val.isdigit() else val
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f)
        settings._config_yaml = None

    return f"✅ Reading budget updated to {val} minutes for future digests."


def _handle_time(args: list[str]) -> str:
    if not args:
        current = settings.app_config.get("digest", {}).get("time", "21:30")
        return f"Current digest delivery time is {current} (Asia/Kolkata). Change with: /time HH:MM (e.g. /time 21:00)."

    time_val = args[0]
    if not re.match(r"^\d{1,2}:\d{2}$", time_val):
        return "Invalid time format. Please provide time as HH:MM in 24-hour format (e.g. /time 21:30)."

    cfg_file = settings.BASE_DIR / "config" / "config.yaml"
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if "digest" not in cfg:
            cfg["digest"] = {}
        cfg["digest"]["time"] = time_val
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f)
        settings._config_yaml = None

    # Reschedule job in scheduler
    from digestif.jobs.scheduler import scheduler_service

    scheduler_service.setup_jobs()

    return f"✅ Daily digest delivery time updated to {time_val}."


def _handle_help() -> str:
    return (
        "<b>📖 Digestif Commands:</b>\n\n"
        "• <b>/today</b> — List today's saved items & status\n"
        "• <b>/digest [min]</b> — Build and deliver digest now\n"
        "• <b>/budget [15|20|30]</b> — Change reading time budget\n"
        "• <b>/time [HH:MM]</b> — Change scheduled delivery time\n"
        "• <b>/help</b> — Show this command list\n\n"
        "<i>Tip: Just share any link, note, or forwarded message directly to save it!</i>"
    )
