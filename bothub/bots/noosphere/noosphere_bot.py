"""
bots/noosphere/noosphere_bot.py — Core task management logic for NoosphereBot.

This module is the single source of truth for task operations.
Both the web UI (routes.py) and the Telegram handler (telegram_handler.py)
call these functions — no logic is duplicated between the two interfaces.

WHAT IS STORED:
  Each task has:
  - group_name  — one of the 7 defined groups (e.g. "Daily", "Job Applications")
  - title       — short description ("Email Karabaşoğlu about thesis")
  - detail      — optional longer note
  - status      — "pending" or "done"
  - created_at  — ISO timestamp
  - updated_at  — ISO timestamp (set when status changes)

GROUPS ORDER:
  Daily is first — it's the most frequently used.
  The rest follow by urgency/type.
"""

from datetime import datetime
from core.database import get_connection

# The 7 task groups — order here controls display order in the UI.
GROUPS = [
    "Daily",
    "PhD Applications",
    "Job Applications",
    "Emails to Send",
    "Code Sessions",
    "Research",
    "Crazy Projects",
]

# Emoji assigned to each group — shown in the web UI and Telegram messages.
GROUP_EMOJI = {
    "Daily":             "📅",
    "PhD Applications":  "🎓",
    "Job Applications":  "💼",
    "Emails to Send":    "📧",
    "Code Sessions":     "💻",
    "Research":          "🔬",
    "Crazy Projects":    "🚀",
}


def add_task(group: str, title: str, detail: str = "") -> int:
    """
    Insert a new pending task into the database.
    Returns the new task's integer ID.
    """
    if group not in GROUPS:
        group = "Daily"   # safe fallback
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO tasks (group_name, title, detail, status, created_at)
           VALUES (?, ?, ?, 'pending', ?)""",
        (group, title.strip(), detail.strip(), now),
    )
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()
    print(f"[Noosphere] Added task #{task_id} to [{group}]: {title}")
    return task_id


def list_tasks(group: str = None, status: str = None) -> list[dict]:
    """
    Return tasks as a list of plain dicts.

    Parameters
    ----------
    group  : filter to a specific group name (or None for all groups)
    status : "pending", "done", or None for all statuses

    Rows are ordered newest first (created_at DESC).
    """
    conditions = []
    params     = []

    if group:
        conditions.append("group_name = ?")
        params.append(group)
    if status:
        conditions.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM tasks {where} ORDER BY created_at DESC"

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    # conn.row_factory = sqlite3.Row makes rows dict-like, but render_template
    # needs proper Python dicts — convert explicitly.
    return [dict(row) for row in rows]


def complete_task(task_id: int):
    """Mark a task as done and record the completion timestamp."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    conn.execute(
        "UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    conn.commit()
    conn.close()
    print(f"[Noosphere] Task #{task_id} marked done.")


def delete_task(task_id: int):
    """Permanently remove a task from the database."""
    conn = get_connection()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    print(f"[Noosphere] Task #{task_id} deleted.")


def pending_summary() -> str:
    """
    Return a formatted plain-text summary of all pending tasks, grouped.
    Used by the Telegram bot to reply to "what's pending?" messages.
    """
    lines = []
    for group in GROUPS:
        tasks = list_tasks(group=group, status="pending")
        if tasks:
            emoji = GROUP_EMOJI.get(group, "📌")
            lines.append(f"\n{emoji} {group}:")
            for t in tasks:
                lines.append(f"  • {t['title']}")

    if not lines:
        return "✅ No pending tasks — you're all caught up!"
    return "Pending tasks:" + "".join(lines)
