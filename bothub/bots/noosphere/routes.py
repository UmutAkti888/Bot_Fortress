"""
bots/noosphere/routes.py — Flask Blueprint for NoosphereBot.

Routes:
  GET  /noosphere              → task dashboard (all groups, pending by default)
  GET  /noosphere?show_done=1  → same but includes completed tasks
  POST /noosphere/add          → add a new task (from the web form)
  POST /noosphere/complete/<id>→ mark a task as done
  POST /noosphere/delete/<id>  → remove a task permanently
"""

from flask import Blueprint, render_template, request, redirect

from bots.noosphere.noosphere_bot import (
    add_task, list_tasks, complete_task, delete_task,
    GROUPS, GROUP_EMOJI,
)

noosphere_bp = Blueprint("noosphere", __name__)


@noosphere_bp.route("/noosphere")
def noosphere():
    """
    Main task dashboard.
    Shows tasks grouped by category. Pending only by default;
    pass ?show_done=1 in the URL to also show completed tasks.
    """
    show_done     = request.args.get("show_done") == "1"
    status_filter = None if show_done else "pending"

    # Load all tasks (filtered by status)
    all_tasks = list_tasks(status=status_filter)

    # Bucket tasks into their groups, preserving GROUPS order
    grouped = {group: [] for group in GROUPS}
    for task in all_tasks:
        g = task["group_name"]
        if g in grouped:
            grouped[g].append(task)
        else:
            # Unknown group name — show it anyway under its own heading
            grouped.setdefault(g, []).append(task)

    # Total pending count (always computed regardless of show_done)
    pending_count = sum(1 for t in list_tasks(status="pending") for _ in [t])

    return render_template(
        "noosphere/noosphere.html",
        grouped=grouped,
        groups=GROUPS,
        group_emoji=GROUP_EMOJI,
        show_done=show_done,
        pending_count=pending_count,
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
