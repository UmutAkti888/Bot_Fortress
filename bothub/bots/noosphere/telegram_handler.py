"""
bots/noosphere/telegram_handler.py — Telegram bot for NoosphereBot.

HOW IT FITS IN:
  app.py starts this module in a background daemon thread alongside Flask.
  The thread polls Telegram for messages continuously until the app exits.

MESSAGE ROUTING — two-stage pipeline:
  Slash commands (registered with Telegram, show in autocomplete):
    /add [group:] title  — add a task, group optional
    /list                — show all pending tasks
    /done <id>           — mark task complete
    /del  <id>           — delete task
    /commands            — quick command reference
    /help                — usage tips and examples

  Stage 1 (fast path): keyword/regex matching for plain-text messages.
    No LLM needed — instant response.
    Handles: "tasks", "done 3", "del 7", "add daily: buy milk"

  Stage 2 (slow path): Ollama NLP for everything else.
    The message is sent to a local model which extracts:
      {"action": "add", "group": "Emails to Send", "title": "email prof"}
    Result is routed to the same CRUD functions as Stage 1.

WHY /add FAILED BEFORE:
  The old handler used `filters.TEXT & ~filters.COMMAND`, which silently
  dropped every message starting with `/`.  Any `/add ...` the user typed
  was ignored.  Now every action has an explicit CommandHandler so
  slash-prefix input works correctly.

WHY POLLING AND NOT WEBHOOKS:
  Webhooks require a public HTTPS URL. Polling works locally with no setup.
  For a personal tool running on your laptop, polling is the right choice.

THREAD SAFETY NOTE:
  noosphere_bot.py opens and closes a SQLite connection per operation,
  so calling it from a thread is safe — no shared connection objects.

WHAT THIS BOT CANNOT DO:
  NoosphereBot is a task manager only.  It cannot send emails, browse the
  web, run code, or take any action outside of adding/listing/completing/
  deleting tasks in the SQLite database.
"""

import asyncio
import json
import os
import re

import requests as req
from telegram import BotCommand, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

from bots.noosphere.noosphere_bot import (
    add_task, list_tasks, complete_task, delete_task,
    pending_summary, GROUPS, GROUP_EMOJI,
)

OLLAMA_URL = "http://localhost:11434/api/chat"

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


# ── Ollama NLP (synchronous — called via asyncio.to_thread) ──────────────────

def _parse_with_ollama(text: str) -> dict:
    """
    Send `text` to a local Ollama model and parse the JSON result.
    Returns a dict with keys: action, group, title, task_id.
    Falls back to {"action": "unknown"} on any error.

    This is a synchronous function — it blocks the calling thread.
    Call it with `await asyncio.to_thread(_parse_with_ollama, text)`
    so the async Telegram event loop isn't blocked.
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
        # Strip markdown code fences the model sometimes adds
        content = re.sub(r"```[a-z]*\n?", "", content).strip()
        return json.loads(content)
    except Exception as e:
        print(f"[Telegram/NLP] Ollama parse failed: {e}")
        return {"action": "unknown"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _match_group(hint: str) -> str | None:
    """
    Fuzzy-match a string to the nearest defined group name.
    Case-insensitive substring match.
    Returns the canonical group name, or None if no match.
    """
    if not hint:
        return None
    h = hint.lower()
    for g in GROUPS:
        if h in g.lower() or g.lower() in h:
            return g
    return None


def _parse_add_args(args: list[str]) -> tuple[str, str]:
    """
    Parse the argument list from a /add command into (group, title).

    Two accepted formats (args is already split on spaces by Telegram):
      /add Buy milk                     → group=Daily,  title="Buy milk"
      /add Research: Read SLAM survey   → group=Research, title="Read SLAM survey"

    The colon can be attached to the group word or separated by a space.
    Returns (group_name, title_string).
    """
    if not args:
        return "Daily", ""

    # Re-join all args into one string for flexible parsing
    text = " ".join(args).strip()

    # Look for "Group: title" pattern (colon anywhere in the first portion)
    m = re.match(r"^(.+?):\s*(.+)$", text)
    if m:
        group = _match_group(m.group(1).strip()) or "Daily"
        title = m.group(2).strip()
    else:
        group = "Daily"
        title = text

    return group, title


# ── Slash command handlers ────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help — full usage guide with examples.
    Covers both slash commands and plain-text fast-path syntax.
    """
    groups_list = "\n".join(f"  {GROUP_EMOJI[g]} {g}" for g in GROUPS)
    help_text = (
        "*NoosphereBot — usage guide*\n\n"

        "*Slash commands* (tap `/` to autocomplete):\n"
        "`/add <title>` — add to Daily\n"
        "`/add <group>: <title>` — add to a specific group\n"
        "`/list` — all pending tasks\n"
        "`/done <id>` — mark task complete\n"
        "`/del <id>` — delete task permanently\n"
        "`/commands` — quick command list\n"
        "`/help` — this message\n\n"

        "*Plain text shortcuts* (no slash needed):\n"
        "`tasks` — show pending\n"
        "`done 3` — complete task #3\n"
        "`del 3` — delete task #3\n"
        "`add Research: read paper` — add to a group\n\n"

        "*Natural language* (Ollama parses these):\n"
        "_Email the professor about thesis revision_\n"
        "_Apply to the Anthropic AI engineer role_\n"
        "_Read the SLAM survey paper tonight_\n\n"

        "*What this bot CANNOT do:*\n"
        "Send emails, browse the web, run code, or take any action "
        "outside of task management.  It is a to-do tracker, not an agent.\n\n"

        "*Task groups:*\n" + groups_list
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /commands — one-screen cheatsheet of every available command.
    Shorter than /help — no examples, just the command signatures.
    """
    text = (
        "*Available commands:*\n\n"
        "`/add <title>` — add task to Daily\n"
        "`/add <group>: <title>` — add to specific group\n"
        "`/list` — show all pending tasks\n"
        "`/done <id>` — mark task as complete\n"
        "`/del <id>` — delete task permanently\n"
        "`/commands` — this list\n"
        "`/help` — full usage guide with examples\n\n"
        "Or just type naturally — Ollama will figure out the action and group."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add [group:] title

    Examples:
      /add Buy milk
      /add Research: Read SLAM survey
      /add Job Applications: Apply to Anthropic
    """
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
            "Please provide a task title.\n"
            "Example: `/add Buy milk`",
            parse_mode="Markdown",
        )
        return

    tid   = add_task(group, title)
    emoji = GROUP_EMOJI.get(group, "")
    await update.message.reply_text(
        f"{emoji} Added to *{group}*\n_{title}_ (#{tid})",
        parse_mode="Markdown",
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/list — show all pending tasks."""
    await update.message.reply_text(pending_summary())


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/done <id> — mark a task complete."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: `/done <task_id>`  — e.g. `/done 5`",
            parse_mode="Markdown",
        )
        return
    tid = int(context.args[0])
    complete_task(tid)
    await update.message.reply_text(f"Done. Task #{tid} marked complete.")


async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/del <id> — delete a task permanently."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: `/del <task_id>`  — e.g. `/del 5`",
            parse_mode="Markdown",
        )
        return
    tid = int(context.args[0])
    delete_task(tid)
    await update.message.reply_text(f"Deleted task #{tid}.")


# ── Main message handler (plain-text fast path + Ollama NLP) ─────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route a plain-text (non-slash) message to the right action.

    STAGE 1 — Fast-path keyword matching (no LLM):
      - "tasks" / "pending"         → pending_summary()
      - "done <n>" / "complete <n>" → complete_task(n)
      - "del <n>" / "delete <n>"    → delete_task(n)
      - "add <group>: <title>"      → add_task(group, title)

    STAGE 2 — Ollama NLP (everything else):
      Sends the message to a local model, gets back structured JSON,
      routes to the same CRUD functions.
    """
    if not update.message or not update.message.text:
        return

    original = update.message.text.strip()
    lower    = original.lower()

    # ── Stage 1: keyword matching ─────────────────────────────────────────────

    # Show all pending tasks
    if lower in ("tasks", "pending", "list", "what's pending?",
                 "what is pending?", "show tasks", "show pending"):
        await update.message.reply_text(pending_summary())
        return

    # "done <id>" / "complete <id>" / "finish <id>"
    m = re.match(r"^(?:done|complete|finish)\s+(\d+)$", lower)
    if m:
        tid = int(m.group(1))
        complete_task(tid)
        await update.message.reply_text(f"Done. Task #{tid} marked complete.")
        return

    # "del <id>" / "delete <id>" / "remove <id>"
    m = re.match(r"^(?:del|delete|remove)\s+(\d+)$", lower)
    if m:
        tid = int(m.group(1))
        delete_task(tid)
        await update.message.reply_text(f"Deleted task #{tid}.")
        return

    # Explicit "add <group>: <title>"
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

    # Show a "thinking" indicator while the LLM runs
    thinking_msg = await update.message.reply_text("...")

    # Run the blocking Ollama call off the event loop thread
    parsed  = await asyncio.to_thread(_parse_with_ollama, original)
    action  = parsed.get("action", "unknown")
    group   = _match_group(parsed.get("group", "")) or "Daily"
    title   = parsed.get("title", original)
    task_id = parsed.get("task_id")

    # Delete the "..." placeholder before sending the real reply
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
            "Try `/add <title>`, `/list`, `/done <id>`, or just describe a task.\n"
            "Type `/commands` to see everything available.\n\n"
            "_Note: this bot manages tasks only — it cannot send emails or "
            "perform actions outside the task list._",
            parse_mode="Markdown",
        )


# ── Entry point (called from app.py in a daemon thread) ──────────────────────

async def _setup_commands(application: Application) -> None:
    """
    Register slash commands with Telegram so they appear in the
    autocomplete menu when the user types '/' in the chat.
    Called automatically by python-telegram-bot via post_init.
    """
    await application.bot.set_my_commands([
        BotCommand("add",      "Add a task: /add [group:] title"),
        BotCommand("list",     "Show all pending tasks"),
        BotCommand("done",     "Mark task done: /done <id>"),
        BotCommand("del",      "Delete a task: /del <id>"),
        BotCommand("commands", "Quick command reference"),
        BotCommand("help",     "Full usage guide with examples"),
    ])


def start_telegram_bot():
    """
    Start the Telegram polling loop.
    Blocks the calling thread indefinitely — run in a daemon thread.

    stop_signals=None: don't install SIGTERM/SIGINT handlers.
    Signal handling must stay in the main thread (owned by Flask).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[Telegram] TELEGRAM_BOT_TOKEN not set — bot not started.")
        return

    async def _run():
        bot_app = (
            Application.builder()
            .token(token)
            .post_init(_setup_commands)   # registers commands in Telegram's menu
            .build()
        )

        # ── Slash command handlers ────────────────────────────────────────────
        bot_app.add_handler(CommandHandler("start",    cmd_help))
        bot_app.add_handler(CommandHandler("help",     cmd_help))
        bot_app.add_handler(CommandHandler("commands", cmd_commands))
        bot_app.add_handler(CommandHandler("add",      cmd_add))
        bot_app.add_handler(CommandHandler("list",     cmd_list))
        bot_app.add_handler(CommandHandler("done",     cmd_done))
        bot_app.add_handler(CommandHandler("del",      cmd_del))

        # ── Plain-text handler (fast path + Ollama NLP) ───────────────────────
        bot_app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )

        print("[Telegram] Bot online — polling for messages.")
        await bot_app.run_polling(stop_signals=None)

    asyncio.run(_run())
