# CLAUDE.md — BotHub Project

## What this project is
A local Flask web app called BotHub — a personal dashboard to run and manage bots from a browser.
Located in `bothub/` inside this repo.

## How to work with this user
- Build one step at a time. Wait for confirmation before moving on.
- Explain every new Flask/web concept in 2-3 sentences.
- Code must be readable and well-commented — user is learning Flask from scratch.
- User background: electronics/robotics engineer, knows Python, FastAPI concepts, ROS2.

## How to run the app
```bash
cd bothub
python app.py
# Visit http://127.0.0.1:5000
```

## Current build progress
- [x] Step 1 — app.py scaffold (single GET / route, Flask basics explained)
- [x] Step 2 — Templates (base.html, index.html, Jinja2 inheritance, render_template)
- [x] Step 3 — arxiv_bot.py (ArXiv API, feedparser, PDF download, results.json)
- [x] Step 4 — Connect bot to Flask (GET/POST /arxiv, /arxiv/download routes)
- [x] Step 5 — arxiv.html: search form, results list, download button, status message
- [ ] Step 6 — CSS polish, README, requirements.txt finalisation

## Planned QoL features (ArXiv bot)
- [ ] Date range filter on search (from year / to year) — ArXiv API supports submittedDate:[YYYYMMDD TO YYYYMMDD]
- [ ] Larger result counts (25, 50, 100 options in dropdown)
- [ ] Bulk paginated download: fetch all pages until year cutoff, download in batches with progress indicator
- [ ] Concept document: brief explanation of major steps and Flask/web concepts used

## Architecture decisions
- Framework: Flask, plain HTML+CSS, no JS frameworks
- Storage: JSON files (results.json), no database
- No authentication — local tool only
- Bot logic lives in bots/ and is kept separate from Flask routing

## Gitignore
- `papers/` — downloaded PDFs
- `results.json` — paper metadata
- `__pycache__/`, `*.pyc`
