"""
core/config.py — Shared path constants for the entire BotHub platform.

WHY THIS EXISTS:
Before restructuring, every bot file calculated its own path to the repo
root using relative ".." tricks. That was fragile — if a file moved, its
path broke. Now all paths live here. Bot modules just import what they need.

HOW REPO_ROOT IS CALCULATED:
  This file lives at: bothub/core/config.py
  Two levels up:      bothub/core/ → bothub/ → Bot_Fortress/
  So REPO_ROOT = Bot_Fortress/ (the git repo root).
"""

import os

# ── Repo root ───────────────────────────────────────────────────────────────
# os.path.dirname(__file__)  = bothub/core/
# one ".."                   = bothub/
# two ".."s                  = Bot_Fortress/   ← this is REPO_ROOT
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

# ── Data files (all at repo root, all gitignored) ───────────────────────────
RESULTS_FILE          = os.path.join(REPO_ROOT, "results.json")
SEMANTIC_RESULTS_FILE = os.path.join(REPO_ROOT, "semantic_results.json")
IEEE_RESULTS_FILE     = os.path.join(REPO_ROOT, "ieee_results.json")
OPENALEX_RESULTS_FILE = os.path.join(REPO_ROOT, "openalex_results.json")
MERGED_FILE           = os.path.join(REPO_ROOT, "merged_results.json")
PROBLEM_MAP_FILE      = os.path.join(REPO_ROOT, "problem_map.json")
PAPERS_DIR            = os.path.join(REPO_ROOT, "papers")

# ── Database (SQLite, repo root, gitignored) ─────────────────────────────────
DB_PATH = os.path.join(REPO_ROOT, "bothub.db")
