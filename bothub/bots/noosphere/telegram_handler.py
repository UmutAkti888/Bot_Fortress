"""
bots/noosphere/telegram_handler.py — Telegram bot for NoosphereBot.

HOW IT FITS IN:
  app.py starts this module in a background daemon thread alongside Flask.
  The thread polls Telegram for messages continuously until the app exits.

MESSAGE ROUTING — two-stage pipeline:
  Slash commands (registered with Telegram, show in autocomplete when
  the user types '/'):
    /start           — welcome message + auto-subscribe to morning briefing
    /help            — full usage guide with examples
    /commands        — quick command cheatsheet
    /add [group:] title — add a task
    /list            — show all pending tasks
    /done <id>       — mark task complete
    /del  <id>       — delete task permanently
    /briefing        — trigger the morning briefing on demand

  Stage 1 (fast path): keyword/regex matching for plain-text messages.
    No LLM — instant response.
    Handles: "tasks", "done 3", "del 7", "add daily: buy milk"

  Stage 2 (slow path): Ollama NLP for everything else.
    Sends message to a local model, gets back structured JSON, routes
    to the same CRUD functions as Stage 1.

MORNING BRIEFING:
  Fires every day at a configured time (BRIEFING_HOUR/BRIEFING_MINUTE in .env).
  Sends a task summary to every chat ID in the briefing_subscribers table.
  Any user who sends /start is auto-subscribed.
  Trigger on demand with /briefing.

  Required .env keys (all optional — sensible defaults apply):
    BRIEFING_HOUR      = 8       (24h, default 8am)
    BRIEFING_MINUTE    = 0       (default :00)
    BRIEFING_TIMEZONE  = Europe/Istanbul   (any IANA tz name)

  Requires: python-telegram-bot[job-queue]  (adds APScheduler)

WHAT THIS BOT CANNOT DO:
  Send emails, browse the web, run code, or take any action outside of
  adding/listing/completing/deleting tasks in the SQLite database.

THREAD SAFETY NOTE:
  noosphere_bot.py opens and closes a SQLite connection per operation,
  so calling it from a thread is safe.
"""

import asyncio
import datetime
import json
import os
import re
from zoneinfo import ZoneInfo         # stdlib since Python 3.9 — no extra dep

import requests as req
from telegram import BotCommand, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

from bots.noosphere.noosphere_bot import (
    add_task, list_tasks, complete_task, delete_task,
    pending_summary, GROUPS, GROUP_EMOJI,
)
from core.database import get_connection

OLLAMA_URL = "http://localhost:11434/api/chat"

# ── Briefing schedule (read once at import time) ──────────────────────────────
_BRIEFING_HOUR   = int(os.environ.get("BRIEFING_HOUR",   "8"))
_BRIEFING_MINUTE = int(os.environ.get("BRIEFING_MINUTE", "0"))
_BRIEFING_TZ     = os.environ.get("BRIEFING_TIMEZONE", "Europe/Istanbul")

# System prompt tells the model to output ONLY JSON — no prose.
_NLP_SYSTEM = (
    "You are a task-bot parser. The user sends a natural language message. "
    "Respond with ONLY a valid JSON object, nothing else.\n"
    "JSON schema:\n"
    '  {"action": "add"|"list"|"complete"|"delete"|"summary"|"unknown",\n'
    '   "group": "<one of the valid groups or Daily if unsure>",\n'
    '   "title": "<task title, only when action is add>",\n'
    '   "task_id": <integer or null>}\n'
    f"Valid groups: {', '.join(GROUPS)}"
)


# ── Subscriber helpers ────────────────────────────────────────────────────────

def _subscribe(chat_id: int, first_name: str, username: str | None) -> None:
    """
    Register a Telegram chat ID for the morning briefing.
    Uses INSERT OR REPLACE so re-running /start is always safe.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO briefing_subscribers (chat_id, first_name, username)
        VALUES (?, ?, ?)
        """,
        (chat_id, first_name, username or ""),
    )
    conn.commit()
    conn.close()


def _get_subscribers() -> list[int]:
    """Return all chat IDs currently subscribed to the morning briefing."""
    conn = get_connection()
    rows = conn.execute("SELECT chat_id FROM briefing_subscribers").fetchall()
    conn.close()
    return [row["chat_id"] for row in rows]


# ── Morning briefing job ──────────────────────────────────────────────────────

async def morning_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Scheduled job: send a task summary to every subscriber.

    Message anatomy:
      🌅 Good morning!
      📋 5 tasks pending:
        📅 Daily  ·  2
        💼 Job Applications  ·  1
        ...
      ⏰ Oldest: Email prof about thesis (12 days ago)
      Type /list to see everything.

    If there are no pending tasks a short "all clear" message is sent instead.
    Errors per-subscriber are caught so one bad chat ID doesn't break others.
    """
    subscribers = _get_subscribers()
    if not subscribers:
        return

    pending = list_tasks(status="pending")

    if not pending:
        text = (
            "🌅 Good morning!\n\n"
            "No pending tasks. You're all caught up! ✅"
        )
    else:
        # Count tasks per group, preserving GROUPS order
        group_counts: dict[str, int] = {}
        for t in pending:
            g = t["group_name"]
            group_counts[g] = group_counts.get(g, 0) + 1

        # Oldest pending task + age in days
        oldest = min(pending, key=lambda t: t["created_at"])
        try:
            oldest_date = datetime.date.fromisoformat(oldest["created_at"][:10])
            age = (datetime.date.today() - oldest_date).days
            age_str = f"{age} day{'s' if age != 1 else ''} ago" if age > 0 else "today"
        except Exception:
            age_str = oldest["created_at"][:10]

        n = len(pending)
        lines = [
            "🌅 Good morning!\n",
            f"📋 *{n} task{'s' if n != 1 else ''} pending:*\n",
        ]
        for g in GROUPS:
            if g in group_counts:
                emoji = GROUP_EMOJI.get(g, "")
                lines.append(f"{emoji} {g}  ·  {group_counts[g]}")

        lines.append(f"\n⏰ Oldest: _{oldest['title']}_ ({age_str})")
        lines.append("\nType /list to see everything.")
        text = "\n".join(lines)

    for chat_id in subscribers:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"[Telegram] Briefing failed for chat {chat_id}: {e}")


# ── Ollama NLP ────────────────────────────────────────────────────────────────

def _parse_with_ollama(text: str) -> dict:
    """
    Send `text` to a local Ollama model and parse the JSON result.
    Returns a dict with keys: action, group, title, task_id.
    Falls back to {"action": "unknown"} on any error.

    Synchronous — call via asyncio.to_thread() to avoid blocking the event loop.
    """
    model = os.environ.get("NOOSPHERE_MODEL", "qwen3.5:0.8b")
    try:
        resp = req.post(
            OLLAMA_URL,
            json={
                "model":    model,
                "messages": [
                    {"role": "system", "content": _NLP_SYSTEM},
                    {"role": "user",   "content": text},
                ],
                "stream": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        content = re.sub(r"```[a-z]*\n?", "", content).strip()
        return json.loads(content)
    except Exception as e:
        print(f"[Telegram/NLP] Ollama parse failed: {e}")
        return {"action": "unknown"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _match_group(hint: str) -> str | None:
    """Fuzzy-match a string to the nearest group name (case-insensitive)."""
    if not hint:
        return None
    h = hint.lower()
    for g in GROUPS:
        if h in g.lower() or g.lower() in h:
            return g
    return None


def _parse_add_args(args: list[str]) -> tuple[str, str]:
    """
    Parse /add command arguments into (group, title).

      /add Buy milk                   → ("Daily", "Buy milk")
      /add Research: Read SLAM survey → ("Research", "Read SLAM survey")
    """
    if not args:
        return "Daily", ""
    text = " ".join(args).strip()
    m = re.match(r"^(.+?):\s*(.+)$", text)
    if m:
        return _match_group(m.group(1).strip()) or "Daily", m.group(2).strip()
    return "Daily", text


# ── Slash command handlers ────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start and /help — full usage guide.
    Also auto-subscribes the user to the morning briefing on /start.
    """
    # Auto-subscribe when /start is used
    if update.message.text and update.message.text.startswith("/start"):
        user = update.effective_user
        _subscribe(
            chat_id    = update.effective_chat.id,
            first_name = user.first_name if user else "User",
            username   = user.username   if user else None,
        )
        sub_note = (
            f"\n✅ *Subscribed to morning briefing* at "
            f"{_BRIEFING_HOUR:02d}:{_BRIEFING_MINUTE:02d} "
            f"({_BRIEFING_TZ}). Use /briefing anytime for a snapshot.\n"
        )
    else:
        sub_note = ""

    groups_list = "\n".join(f"  {GROUP_EMOJI[g]} {g}" for g in GROUPS)
    help_text = (
        "*NoosphereBot — usage guide*\n"
        + sub_note + "\n"
        "*Slash commands* (tap / to autocomplete):\n"
        "`/add <title>` — add to Daily\n"
        "`/add <group>: <title>` — add to a specific group\n"
        "`/list` — all pending tasks\n"
        "`/done <id>` — mark task complete\n"
        "`/del <id>` — delete task permanently\n"
        "`/briefing` — show morning summary now\n"
        "`/commands` — quick command list\n"
        "`/help` — this message\n\n"

        "*Plain text shortcuts* (no slash):\n"
        "`tasks` — show pending\n"
        "`done 3` — complete task #3\n"
        "`del 3` — delete task #3\n"
        "`add Research: read paper` — add to group\n\n"

        "*Natural language* (Ollama parses these):\n"
        "_Email the professor about thesis revision_\n"
        "_Apply to the Anthropic AI engineer role_\n"
        "_Read the SLAM survey paper tonight_\n\n"

        "*What this bot CANNOT do:*\n"
        "Send emails, browse the web, run code, or take any action "
        "outside of task management.\n\n"

        "*Task groups:*\n" + groups_list
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/commands — one-screen cheatsheet."""
    text = (
        "*Available commands:*\n\n"
        "`/add <title>` — add task to Daily\n"
        "`/add <group>: <title>` — add to specific group\n"
        "`/list` — show all pending tasks\n"
        "`/done <id>` — mark task as complete\n"
        "`/del <id>` — delete task permanently\n"
        "`/briefing` — show morning summary now\n"
        "`/commands` — this list\n"
        "`/help` — full usage guide\n\n"
        "Or just type naturally — Ollama figures out the action and group."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /briefing — trigger the morning briefing on demand.
    Useful for testing the schedule and for a quick task snapshot any time.
    Sends the message directly to this chat rather than all subscribers.
    """
    # Reuse the same job callback but target only this chat
    pending = list_tasks(status="pending")

    if not pending:
        text = (
            "📋 *Task snapshot*\n\n"
            "No pending tasks. You're all caught up! ✅"
        )
    else:
        group_counts: dict[str, int] = {}
        for t in pending:
            g = t["group_name"]
            group_counts[g] = group_counts.get(g, 0) + 1

        oldest = min(pending, key=lambda t: t["created_at"])
        try:
            oldest_date = datetime.date.fromisoformat(oldest["created_at"][:10])
            age = (datetime.date.today() - oldest_date).days
            age_str = f"{age} day{'s' if age != 1 else ''} ago" if age > 0 else "today"
        except Exception:
            age_str = oldest["created_at"][:10]

        n = len(pending)
        lines = [
            "📋 *Task snapshot*\n",
            f"*{n} task{'s' if n != 1 else ''} pending:*\n",
        ]
        for g in GROUPS:
            if g in group_counts:
                emoji = GROUP_EMOJI.get(g, "")
                lines.append(f"{emoji} {g}  ·  {group_counts[g]}")

        lines.append(f"\n⏰ Oldest: _{oldest['title']}_ ({age_str})")
        lines.append("\nType /list to see everything.")
        text = "\n".join(lines)

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add [group:] title"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/add <title>` or `/add <group>: <title>`\n\n"
            "Example: `/add Research: Read SLAM survey`",
            parse_mode="Markdown",
        )
        return

    group, title = _parse_add_args(context.args)
    if not title:
        await update.message.reply_text(
            "Please provide a task title.\nExample: `/add Buy milk`",
            parse_mode="Markdown",
        )
        return

    tid   = add_task(group, title)
    emoji = GROUP_EMOJI.get(group, "")
    await update.message.reply_text(
        f"{emoji} Added to *{group}*\n_{title}_ (#{tid})",
        parse_mode="Markdown",
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/list — all pending tasks."""
    await update.message.reply_text(pending_summary())


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done <id>"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: `/done <task_id>`  — e.g. `/done 5`",
            parse_mode="Markdown",
        )
        return
    tid = int(context.args[0])
    complete_task(tid)
    await update.message.reply_text(f"Done. Task #{tid} marked complete.")


async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/del <id>"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: `/del <task_id>`  — e.g. `/del 5`",
            parse_mode="Markdown",
        )
        return
    tid = int(context.args[0])
    delete_task(tid)
    await update.message.reply_text(f"Deleted task #{tid}.")


# ── Plain-text handler (fast path + Ollama NLP) ───────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Route a plain-text (non-slash) message.

    Stage 1 — fast keyword matching (no LLM):
      "tasks" / "pending"          → pending_summary()
      "done <n>" / "complete <n>"  → complete_task(n)
      "del <n>"  / "delete <n>"    → delete_task(n)
      "add <group>: <title>"       → add_task(group, title)

    Stage 2 — Ollama NLP for everything else.
    """
    if not update.message or not update.message.text:
        return

    original = update.message.text.strip()
    lower    = original.lower()

    # Show all pending tasks
    if lower in ("tasks", "pending", "list", "what's pending?",
                 "what is pending?", "show tasks", "show pending"):
        await update.message.reply_text(pending_summary())
        return

    # "done/complete/finish <id>"
    m = re.match(r"^(?:done|complete|finish)\s+(\d+)$", lower)
    if m:
        tid = int(m.group(1))
        complete_task(tid)
        await update.message.reply_text(f"Done. Task #{tid} marked complete.")
        return

    # "del/delete/remove <id>"
    m = re.match(r"^(?:del|delete|remove)\s+(\d+)$", lower)
    if m:
        tid = int(m.group(1))
        delete_task(tid)
        await update.message.reply_text(f"Deleted task #{tid}.")
        return

    # "add <group>: <title>"
    m = re.match(r"^add\s+(.+?):\s+(.+)$", original, re.IGNORECASE)
    if m:
        group = _match_group(m.group(1).strip()) or "Daily"
        title = m.group(2).strip()
        tid   = add_task(group, title)
        emoji = GROUP_EMOJI.get(group, "")
        await update.message.reply_text(
            f"{emoji} Added to *{group}*\n_{title}_ (#{tid})",
            parse_mode="Markdown",
        )
        return

    # ── Stage 2: Ollama NLP ───────────────────────────────────────────────────
    thinking_msg = await update.message.reply_text("...")
    parsed  = await asyncio.to_thread(_parse_with_ollama, original)
    action  = parsed.get("action", "unknown")
    group   = _match_group(parsed.get("group", "")) or "Daily"
    title   = parsed.get("title", original)
    task_id = parsed.get("task_id")

    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if action == "add":
        tid   = add_task(group, title)
        emoji = GROUP_EMOJI.get(group, "")
        await update.message.reply_text(
            f"{emoji} Added to *{group}*\n_{title}_ (#{tid})",
            parse_mode="Markdown",
        )
    elif action in ("summary", "list") and not task_id:
        await update.message.reply_text(pending_summary())
    elif action == "list" and group:
        tasks = list_tasks(group=group, status="pending")
        if tasks:
            lines = [f"*{group}* — pending:"]
            for t in tasks:
                lines.append(f"  #{t['id']} {t['title']}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"Nothing pending in {group}.")
    elif action == "complete" and task_id:
        complete_task(int(task_id))
        await update.message.reply_text(f"Done. Task #{task_id} marked complete.")
    elif action == "delete" and task_id:
        delete_task(int(task_id))
        await update.message.reply_text(f"Deleted task #{task_id}.")
    else:
        await update.message.reply_text(
            "I couldn't work out what to do with that.\n\n"
            "Try `/add <title>`, `/list`, `/done <id>`, or describe a task.\n"
            "Type `/commands` to see everything available.\n\n"
            "_Note: this bot manages tasks only — it cannot send emails or "
            "perform actions outside the task list._",
            parse_mode="Markdown",
        )


# ── Telegram command menu (shown when user types /) ───────────────────────────

async def _setup_commands(application: Application) -> None:
    """Register slash commands with Telegram for autocomplete."""
    await application.bot.set_my_commands([
        BotCommand("add",      "Add a task: /add [group:] title"),
        BotCommand("list",     "Show all pending tasks"),
        BotCommand("done",     "Mark task done: /done <id>"),
        BotCommand("del",      "Delete a task: /del <id>"),
        BotCommand("briefing", "Show morning task summary now"),
        BotCommand("commands", "Quick command reference"),
        BotCommand("help",     "Full usage guide with examples"),
    ])


# ── Entry point ───────────────────────────────────────────────────────────────

def start_telegram_bot() -> None:
    """
    Start the Telegram polling loop and schedule the morning briefing.
    Blocks the calling thread — run in a daemon thread from app.py.
    stop_signals=None keeps signal handling in Flask's main thread.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[Telegram] TELEGRAM_BOT_TOKEN not set — bot not started.")
        return

    async def _run():
        bot_app = (
            Application.builder()
            .token(token)
            .post_init(_setup_commands)
            .build()
        )

        # ── Slash command handlers ────────────────────────────────────────────
        bot_app.add_handler(CommandHandler("start",    cmd_help))
        bot_app.add_handler(CommandHandler("help",     cmd_help))
        bot_app.add_handler(CommandHandler("commands", cmd_commands))
        bot_app.add_handler(CommandHandler("briefing", cmd_briefing))
        bot_app.add_handler(CommandHandler("add",      cmd_add))
        bot_app.add_handler(CommandHandler("list",     cmd_list))
        bot_app.add_handler(CommandHandler("done",     cmd_done))
        bot_app.add_handler(CommandHandler("del",      cmd_del))

        # ── Plain-text handler ────────────────────────────────────────────────
        bot_app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )

        # ── Morning briefing schedule ─────────────────────────────────────────
        # JobQueue is available when python-telegram-bot[job-queue] is installed.
        # If APScheduler is missing the job_queue attribute will be None and we
        # skip scheduling gracefully rather than crashing.
        if bot_app.job_queue is not None:
            try:
                tz            = ZoneInfo(_BRIEFING_TZ)
                briefing_time = datetime.time(
                    hour=_BRIEFING_HOUR,
                    minute=_BRIEFING_MINUTE,
                    tzinfo=tz,
                )
                bot_app.job_queue.run_daily(
                    morning_briefing,
                    time=briefing_time,
                    name="morning_briefing",
                )
                print(
                    f"[Telegram] Morning briefing scheduled at "
                    f"{_BRIEFING_HOUR:02d}:{_BRIEFING_MINUTE:02d} {_BRIEFING_TZ}"
                )
            except Exception as e:
                print(f"[Telegram] Could not schedule briefing: {e}")
        else:
            print(
                "[Telegram] JobQueue unavailable — "
                "install python-telegram-bot[job-queue] for scheduled briefings."
            )

        print("[Telegram] Bot online — polling for messages.")
        await bot_app.run_polling(stop_signals=None)

    asyncio.run(_run())
