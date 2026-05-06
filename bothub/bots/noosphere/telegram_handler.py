"""
bots/noosphere/telegram_handler.py — Telegram bot for NoosphereBot.

HOW IT FITS IN:
  app.py starts this module in a background daemon thread alongside Flask.
  The thread polls Telegram for messages continuously until the app exits.

MESSAGE ROUTING — two-stage pipeline:
  Stage 1 (fast path): keyword/regex matching for common commands.
    No LLM needed — instant response.
    Handles: "tasks", "done 3", "del 7", "add daily: buy milk"

  Stage 2 (slow path): Ollama NLP for everything else.
    The message is sent to a local model which extracts:
      {"action": "add", "group": "Emails to Send", "title": "email prof"}
    Result is routed to the same CRUD functions as Stage 1.

WHY POLLING AND NOT WEBHOOKS:
  Webhooks require a public HTTPS URL. Polling works locally with no setup.
  For a personal tool running on your laptop, polling is the right choice.

THREAD SAFETY NOTE:
  noosphere_bot.py opens and closes a SQLite connection per operation,
  so calling it from a thread is safe — no shared connection objects.
"""

import asyncio
import json
import os
import re

import requests as req
from telegram import Update
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


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start and /help — explain what the bot can do."""
    groups_list = "\n".join(f"  {GROUP_EMOJI[g]} {g}" for g in GROUPS)
    help_text = (
        "*NoosphereBot* — task tracker\n\n"
        "*Quick commands:*\n"
        "`tasks` — show all pending tasks\n"
        "`done <id>` — mark a task complete\n"
        "`del <id>` — delete a task\n\n"
        "*Natural language (Ollama parses these):*\n"
        "Just type what you want — the bot guesses the group.\n"
        "_Examples:_\n"
        "  Email the professor about thesis revision\n"
        "  Apply to the Anthropic AI engineer role\n"
        "  Read the SLAM survey paper tonight\n\n"
        "*Task groups:*\n" + groups_list
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ── Main message handler ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route an incoming text message to the right action.

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
            "I couldn't work out what to do with that.\n"
            "Try: `tasks`, `done <id>`, or just describe what you want to add.",
            parse_mode="Markdown",
        )


# ── Entry point (called from app.py in a daemon thread) ──────────────────────

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
        bot_app = Application.builder().token(token).build()
        bot_app.add_handler(CommandHandler("start", cmd_start))
        bot_app.add_handler(CommandHandler("help",  cmd_start))
        bot_app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        print("[Telegram] Bot online — polling for messages.")
        await bot_app.run_polling(stop_signals=None)

    asyncio.run(_run())
