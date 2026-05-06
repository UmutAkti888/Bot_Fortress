"""
app.py — BotHub entry point.

WHAT THIS FILE DOES (and what it deliberately does NOT do):
  - Creates the Flask app
  - Loads .env so API keys are available before any bot module is imported
  - Registers each bot module's Blueprint (their routes join the app here)
  - Defines the / dashboard route
  - Calls init_db() so the database is ready on first run
  - Starts the Telegram bot in a background daemon thread
  - Starts the Flask dev server

Everything else lives in the bot modules:
  - bothub/bots/literature/routes.py    ← all /arxiv, /semantic, /ieee, etc.
  - bothub/bots/noosphere/routes.py     ← all /noosphere routes
  - bothub/bots/noosphere/telegram_handler.py  ← Telegram polling loop
  - bothub/core/                        ← shared infrastructure

IMPORT ORDER MATTERS:
  .env must be loaded BEFORE importing bot modules, because the bot files
  read API keys like SEMANTIC_API_KEY at module level (os.environ.get(...)
  runs when the file is first imported). Loading .env after would be too late.

TELEGRAM + FLASK THREAD NOTE:
  Flask's debug mode (use_reloader=True) forks a child process to handle
  requests. The child sets WERKZEUG_RUN_MAIN=true. We start the Telegram
  thread only in that child — never in the parent file-watcher process.
  This prevents two bot instances from running simultaneously on reload.
"""

import os
from flask import Flask, render_template

# ── Step 1: Load .env before importing any bot module ───────────────────────
# REPO_ROOT = Bot_Fortress/ (one level above this file's folder: bothub/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except ImportError:
    pass  # python-dotenv not installed — keys must be in system env vars

# ── Step 2: Import bot Blueprints ────────────────────────────────────────────
# Importing these triggers the bot module files to load, which is why .env
# must be loaded first (the bot files read API keys at import time).
from bots.literature.routes import literature_bp
from bots.noosphere.routes  import noosphere_bp

# ── Step 3: Import shared infrastructure ─────────────────────────────────────
from core.database import init_db

# ── Step 4: Create the Flask app ─────────────────────────────────────────────
app = Flask(__name__)

# ── Step 5: Register Blueprints ───────────────────────────────────────────────
# This is what "adds" all the bot routes to the app.
# After register_blueprint(), every @literature_bp.route("/arxiv") becomes
# reachable at http://127.0.0.1:5000/arxiv — as if it had been written here.
app.register_blueprint(literature_bp)
app.register_blueprint(noosphere_bp)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()          # create database tables if they don't exist yet

    # ── Start Telegram bot in background thread ───────────────────────────────
    # We only start it in Werkzeug's child process (WERKZEUG_RUN_MAIN=true).
    # In debug mode Flask forks: parent = file watcher, child = actual server.
    # Starting the thread in the parent would create a second bot instance on
    # every file-change reload. The child re-runs this block with the env var
    # set, so the thread starts exactly once per Flask session.
    import threading
    from bots.noosphere.telegram_handler import start_telegram_bot

    # True when we're in the actual server process (not the file-watcher parent).
    # In debug mode Flask forks: WERKZEUG_RUN_MAIN marks the server child.
    # Outside debug mode there is no fork, so always start.
    _is_server_process = (
        os.environ.get("WERKZEUG_RUN_MAIN") == "true"  # debug reloader child
        or not app.debug                                 # non-debug / production
    )
    if _is_server_process:
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if tg_token:
            tg_thread = threading.Thread(target=start_telegram_bot, daemon=True)
            tg_thread.start()
        else:
            print("[BotHub] TELEGRAM_BOT_TOKEN not set — Telegram bot skipped.")

    app.run(debug=True)
