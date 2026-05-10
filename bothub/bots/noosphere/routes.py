"""
bots/noosphere/routes.py — Flask Blueprint for NoosphereBot.

Routes:
  GET  /noosphere              → task dashboard (all groups, pending by default)
  GET  /noosphere?show_done=1  → same but includes completed tasks
  POST /noosphere/add          → add a new task (from the web form)
  POST /noosphere/complete/<id>→ mark a task as done
  POST /noosphere/delete/<id>  → remove a task permanently
"""

import os
import requests as req
from flask import Blueprint, render_template, request, redirect

from bots.noosphere.noosphere_bot import (
    add_task, list_tasks, complete_task, delete_task,
    GROUPS, GROUP_EMOJI,
)

noosphere_bp = Blueprint("noosphere", __name__)


def _get_telegram_bot_info() -> dict | None:
    """
    Call the Telegram Bot API to get this bot's username and display name.
    Returns a dict like {"username": "mybot", "first_name": "NoosphereBot"}
    or None if the token is missing or the call fails.
    Used to show the bot link on the web UI so the user knows where to find it.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None
    try:
        r = req.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=4,
        )
        if r.ok:
            return r.json().get("result")
    except Exception:
        pass
    return None


@noosphere_bp.route("/noosphere")
def noosphere():
    """
    Main task dashboard.
    Shows tasks grouped by category. Pending only by default;
    pass ?show_done=1 in the URL to also show completed tasks.
    """
    show_done     = request.args.get("show_done") == "1"
    status_filter = None if show_done else "pending"

    # Load tasks for display (filtered by status toggle)
    all_tasks = list_tasks(status=status_filter)

    # Bucket tasks into their groups, preserving GROUPS order
    grouped = {group: [] for group in GROUPS}
    for task in all_tasks:
        g = task["group_name"]
        if g in grouped:
            grouped[g].append(task)
        else:
            grouped.setdefault(g, []).append(task)

    # Counts — always from the full table regardless of the display toggle
    pending_count = len(list_tasks(status="pending"))
    done_count    = len(list_tasks(status="done"))
    total_count   = pending_count + done_count

    # Telegram bot info — fetched live so the page shows the correct bot link
    tg_bot = _get_telegram_bot_info()

    return render_template(
        "noosphere/noosphere.html",
        grouped=grouped,
        groups=GROUPS,
        group_emoji=GROUP_EMOJI,
        show_done=show_done,
        pending_count=pending_count,
        done_count=done_count,
        total_count=total_count,
        tg_bot=tg_bot,
        tg_token_set=bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
    )


@noosphere_bp.route("/noosphere/add", methods=["POST"])
def noosphere_add():
    """Add a task from the web form and redirect back to the dashboard."""
    group  = request.form.get("group",  GROUPS[0])
    title  = request.form.get("title",  "").strip()
    detail = request.form.get("detail", "").strip()
    if title:
        add_task(group, title, detail)
    return redirect("/noosphere")


@noosphere_bp.route("/noosphere/complete/<int:task_id>", methods=["POST"])
def noosphere_complete(task_id):
    """Mark a task as done."""
    complete_task(task_id)
    # Go back to wherever the user was (pending or done view)
    return redirect(request.referrer or "/noosphere")


@noosphere_bp.route("/noosphere/delete/<int:task_id>", methods=["POST"])
def noosphere_delete(task_id):
    """Delete a task permanently."""
    delete_task(task_id)
    return redirect(request.referrer or "/noosphere")
