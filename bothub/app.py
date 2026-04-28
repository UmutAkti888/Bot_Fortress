"""
app.py — BotHub entry point.

WHAT THIS FILE DOES (and what it deliberately does NOT do):
  - Creates the Flask app
  - Loads .env so API keys are available before any bot module is imported
  - Registers each bot module's Blueprint (their routes join the app here)
  - Defines the / dashboard route
  - Calls init_db() so the database is ready on first run
  - Starts the dev server

Everything else lives in the bot modules:
  - bothub/bots/literature/routes.py  ← all /arxiv, /semantic, /ieee, etc.
  - bothub/bots/noosphere/routes.py   ← all /noosphere routes (Phase 2)
  - bothub/core/                      ← shared infrastructure

IMPORT ORDER MATTERS:
  .env must be loaded BEFORE importing bot modules, because the bot files
  read API keys like SEMANTIC_API_KEY at module level (os.environ.get(...)
  runs when the file is first imported). Loading .env after would be too late.
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
    app.run(debug=True)
