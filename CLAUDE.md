# CLAUDE.md — BotHub Project

## What this project is
A local Flask web app called BotHub — a personal dashboard to run and manage bots from a browser.
Located in `bothub/` inside this repo.

## How to work with this user
- Build one step at a time. Wait for confirmation before moving on.
- Explain every new Flask/web concept in 2-3 sentences.
- Code must be readable and well-commented — user is learning Flask from scratch.
- User background: electronics/robotics engineer, knows Python, FastAPI concepts, ROS2.
- IMPORTANT: Stop Flask (Ctrl+C) before editing files mid-session to avoid reload cutting active connections.

## How to run the app
```bash
cd bothub
python app.py
# Visit http://127.0.0.1:5000
```

## Prerequisites
- Ollama must be running for Lit Review Assistant: `ollama serve`
- Recommended: enable "Start on login" in Ollama tray settings

## Current build progress
- [x] Step 1 — app.py scaffold (single GET / route, Flask basics explained)
- [x] Step 2 — Templates (base.html, index.html, Jinja2 inheritance, render_template)
- [x] Step 3 — arxiv_bot.py (ArXiv API, feedparser, PDF download, results.json)
- [x] Step 4 — Connect bot to Flask (GET/POST /arxiv, /arxiv/download routes)
- [x] Step 5 — arxiv.html: search form, results list, download button, status message
- [x] Step 6 (partial) — CSS polish, requirements.txt updated

## Bots built
| Bot | Route | File | Status |
|---|---|---|---|
| ArXiv Paper Fetcher | /arxiv | bots/arxiv_bot.py | ✅ Complete |
| Semantic Scholar | /semantic | bots/semantic_scholar_bot.py | ✅ Complete |
| Lit Review Assistant | /litreview | bots/lit_review_bot.py | ✅ Working |

## Features completed
- [x] Keyword search (ArXiv + Semantic Scholar)
- [x] Date range filter (from/to year)
- [x] Result counts up to 100
- [x] Download All PDFs
- [x] Export to CSV (UTF-8 BOM for Excel)
- [x] Citation counts (Semantic Scholar)
- [x] LLM analysis via Ollama SSE streaming (token-by-token)
- [x] Markdown rendering of LLM output
- [x] Model selector (reads installed Ollama models dynamically)

## Planned features
- [ ] Bulk paginated download with progress indicator
- [ ] Semantic Scholar CSV export (currently ArXiv only)
- [ ] Ollama status indicator on Lit Review page
- [ ] Concept document explaining pipeline and Flask concepts
- [ ] README with full setup instructions
- [ ] Remote/autonomous agent pipeline (future phase)

## Architecture decisions
- Framework: Flask, plain HTML+CSS, minimal vanilla JS (SSE streaming only)
- Storage: JSON files (results.json, semantic_results.json), no database
- No authentication — local tool only
- Bot logic lives in bots/ (repo root) — decoupled from Flask routing
- LLM: Ollama local inference, model selectable in UI

## Repo structure
```
Bot_Fortress/
├── bots/                    ← standalone bot logic
│   ├── arxiv_bot.py
│   ├── semantic_scholar_bot.py
│   └── lit_review_bot.py
├── bothub/                  ← Flask dashboard
│   ├── app.py
│   ├── templates/
│   └── static/
├── papers/                  ← gitignored
├── results.json             ← gitignored
└── semantic_results.json    ← gitignored
```

## Gitignore
- `papers/` — downloaded PDFs
- `results.json`, `semantic_results.json` — search result caches
- `__pycache__/`, `*.pyc`
- `bothub/system_map.txt`
- `.claude/settings.local.json`

## Known hardware note
- User has RTX 3060 Laptop (6GB VRAM)
- Running games alongside Ollama will exhaust VRAM — close game before using Lit Review Assistant
- qwen3.5:0.8b confirmed working when VRAM is available
