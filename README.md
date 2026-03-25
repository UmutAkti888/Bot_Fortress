This repo will be filled with various bot projects, aimed towards various tasks of various importance.
Moreover, the repo will be co-maintained and co-proctored by Claude (Anthropic).

---

# Bot Fortress — BotHub

A local Flask web dashboard for running and managing research bots from a browser.
Built for personal academic research — no cloud, no database, no authentication required.

---

## What is BotHub?

BotHub is a personal tool that lets you search multiple academic databases,
collect paper metadata, and run local LLM analysis — all from a single browser interface.

Designed for researchers who want to automate the early stages of a literature review
without depending on cloud services or expensive APIs.

---

## Bots

| Bot | Route | Description |
|---|---|---|
| ArXiv Paper Fetcher | `/arxiv` | Search ArXiv by keyword. Filter by year range. Download PDFs. Export to CSV. |
| Semantic Scholar | `/semantic` | Search Semantic Scholar. Results ranked by citation count. Export to CSV. |
| IEEE Xplore | `/ieee` | Search IEEE's database. Requires a free API key. Citation counts, DOI links. |
| Merge & Deduplicate | `/merge` | Combine results from all three sources. Removes duplicate papers by DOI and title. |
| Lit Review Assistant | `/litreview` | Send paper results to a local LLM via Ollama. Identifies themes, gaps, reading priorities. |

---

## Literature Review Workflow

This is the recommended workflow for conducting a systematic literature review:

```
1. COLLECT
   ├── ArXiv Bot        → search keywords, export results
   ├── Semantic Scholar → search same keywords, note citation counts
   └── IEEE Xplore      → search same keywords (requires free API key)

2. MERGE
   └── Merge & Deduplicate → combines all three sources,
       removes papers that appear in multiple databases
       Result: one clean, deduplicated list

3. ANALYSE
   └── Lit Review Assistant → sends merged results to local LLM
       Tasks: identify themes / rank by importance /
              find research gaps / one-line summaries
       Recommended: DeepSeek or Qwen 4B+ for 50-100 paper batches

4. EXPORT & SYNTHESISE
   └── Copy the analysis output into a Word document
       Feed to Claude (claude.ai) for final synthesis
       and literature review drafting
```

**Why merge before analysing?**
The same highly-cited paper often appears in all three databases.
Without deduplication, the LLM sees duplicates, skewing theme detection
and wasting context window space.

---

## Setup

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) — for the Lit Review Assistant (local LLM inference)
- IEEE Xplore API key (free) — from [developer.ieee.org](https://developer.ieee.org)

### Install

```bash
git clone https://github.com/UmutAkti888/Bot_Fortress.git
cd Bot_Fortress/bothub
pip install -r requirements.txt
```

### Configure IEEE API key (optional)

Create a `.env` file at the repo root:

```
IEEE_API_KEY=your_key_here
```

This file is gitignored — your key is never committed to the repo.

### Run

```bash
cd bothub
python app.py
# Visit http://127.0.0.1:5000
```

### Start Ollama (for Lit Review Assistant)

```bash
ollama serve
ollama pull qwen3.5:0.8b    # lightweight, fast
# or
ollama pull qwen3.5:4b      # better quality for large paper sets
```

---

## Hardware Notes

- The Lit Review Assistant requires Ollama to be running (`ollama serve`).
- Running GPU-intensive applications alongside Ollama exhausts VRAM
  and causes very slow or failed LLM responses. Close them first.
- Tested on: RTX 3060 Laptop GPU (6GB VRAM), Windows 11.

---

## Repo Structure

```
Bot_Fortress/
├── bots/                    ← standalone bot logic (no Flask dependency)
│   ├── arxiv_bot.py
│   ├── semantic_scholar_bot.py
│   ├── ieee_bot.py
│   ├── merge_bot.py
│   └── lit_review_bot.py
├── bothub/                  ← Flask web dashboard
│   ├── app.py               ← routes and server entry point
│   ├── templates/           ← Jinja2 HTML templates
│   └── static/style.css
├── papers/                  ← downloaded PDFs (gitignored)
├── .env                     ← API keys (gitignored — never committed)
└── .env.example             ← template for .env setup
```

**Design decisions:**
- Bot logic in `bots/` is decoupled from Flask — runs standalone or via web UI
- Flat JSON file storage — no database
- Local only — no authentication needed
- LLM via Ollama — fully offline, model-selectable in UI

---

## Built With

- [Flask](https://flask.palletsprojects.com/) — web framework
- [feedparser](https://feedparser.readthedocs.io/) — ArXiv XML parsing
- [requests](https://docs.python-requests.org/) — HTTP calls
- [markdown](https://python-markdown.github.io/) — LLM output rendering
- [Ollama](https://ollama.ai) — local LLM inference
- [python-dotenv](https://pypi.org/project/python-dotenv/) — API key loading
