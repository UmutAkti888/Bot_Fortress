"""
bots/noosphere/routes.py — Flask Blueprint for the Noosphere task tracker.

Phase 2 will fill this in with:
  - GET  /noosphere          → task dashboard (web UI)
  - POST /noosphere/add      → add a task (from web or Telegram)
  - POST /noosphere/complete → mark a task done
  - GET  /noosphere/pending  → JSON list of pending tasks (for Telegram polling)

For now this is a placeholder that registers the /noosphere route and
renders a "coming soon" page, so the nav link works immediately.
"""

from flask import Blueprint, render_template

noosphere_bp = Blueprint("noosphere", __name__)


@noosphere_bp.route("/noosphere")
def noosphere():
    """Placeholder page — will be replaced in Phase 2."""
    return render_template("noosphere/noosphere.html")
