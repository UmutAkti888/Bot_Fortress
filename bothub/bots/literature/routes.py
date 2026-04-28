"""
bots/literature/routes.py — Flask Blueprint for all Literature Review routes.

WHAT IS A BLUEPRINT?
A Blueprint is Flask's way of splitting a large app into independent modules.
Think of it like a mini-Flask app: it defines routes with @literature_bp.route(...)
instead of @app.route(...). The main app.py then registers it with:
    app.register_blueprint(literature_bp)
After registration, all routes defined here become part of the main app — exactly
as if they'd been written directly in app.py. The URLs don't change at all.

WHY USE ONE HERE?
Before restructuring, app.py was 610 lines covering 7 different bots.
Now each bot module owns its routes. app.py stays thin and readable.
"""

import csv
import io
import json
import os

import markdown as md_lib
import requests
from flask import (
    Blueprint, Response, jsonify,
    render_template, request, stream_with_context,
)

from bots.literature.arxiv_bot          import search, download_pdfs
from bots.literature.semantic_scholar_bot import search as semantic_search
from bots.literature.lit_review_bot     import load_papers, build_prompt, SYSTEM_MESSAGE
from bots.literature.ieee_bot           import search as ieee_search
from bots.literature.merge_bot          import merge_all, SOURCE_FILES, _read_source_file
from bots.literature.openalex_bot       import search as openalex_search
from bots.literature.problem_map_bot    import extract_problems_stream, load_problem_map
from core.config import (
    RESULTS_FILE, SEMANTIC_RESULTS_FILE, IEEE_RESULTS_FILE,
    OPENALEX_RESULTS_FILE, MERGED_FILE,
)
from core.ollama import get_models

# ── Blueprint declaration ────────────────────────────────────────────────────
# "literature" is the internal name — used for url_for() calls if needed.
# No url_prefix means routes stay at /arxiv, /semantic etc. (not /literature/arxiv).
literature_bp = Blueprint("literature", __name__)


# ── AcademiBot hub page ───────────────────────────────────────────────────────

@literature_bp.route("/academibot")
def academibot():
    """AcademiBot sub-dashboard — shows all literature research tools as cards."""
    return render_template("academibot.html")


# ── Shared helper ────────────────────────────────────────────────────────────

def _read_papers(filepath: str) -> list:
    """
    Load papers from a results JSON file, handling both formats:
    - Old flat format:   [ {...}, {...} ]
    - New wrapped format: { "_query": {...}, "papers": [...] }
    Returns an empty list if the file doesn't exist.
    """
    if not os.path.exists(filepath):
        return []
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("papers", [])


# ── ArXiv routes ─────────────────────────────────────────────────────────────

@literature_bp.route("/arxiv", methods=["GET", "POST"])
def arxiv():
    if request.method == "POST":
        raw_keywords = request.form.get("keywords", "")
        max_results  = int(request.form.get("max_results", 10))
        keywords     = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]

        from_year = request.form.get("from_year", "").strip()
        to_year   = request.form.get("to_year",   "").strip()
        from_year = int(from_year) if from_year.isdigit() else None
        to_year   = int(to_year)   if to_year.isdigit()   else None

        papers = search(keywords, max_results=max_results,
                        from_year=from_year, to_year=to_year)

        return render_template(
            "literature/arxiv.html",
            papers=papers, last_query=raw_keywords,
            max_results=max_results,
            from_year=from_year or "", to_year=to_year or "",
            searched=True,
        )

    return render_template(
        "literature/arxiv.html",
        papers=[], last_query="", max_results=10,
        from_year="", to_year="", searched=False,
    )


@literature_bp.route("/arxiv/download", methods=["POST"])
def arxiv_download():
    papers      = _read_papers(RESULTS_FILE)
    downloaded  = download_pdfs(papers)
    last_query  = request.form.get("last_query",  "")
    max_results = int(request.form.get("max_results", 10))
    from_year   = request.form.get("from_year", "")
    to_year     = request.form.get("to_year",   "")

    return render_template(
        "literature/arxiv.html",
        papers=papers, last_query=last_query,
        max_results=max_results, from_year=from_year, to_year=to_year,
        searched=True,
        download_status=f"Downloaded {len(downloaded)} PDF(s) to the papers/ folder.",
    )


@literature_bp.route("/arxiv/export", methods=["POST"])
def arxiv_export():
    papers = _read_papers(RESULTS_FILE)
    output = io.StringIO()
    output.write('﻿')   # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Published", "Abstract", "ArXiv Link", "PDF Link"])
    for paper in papers:
        authors_str = ", ".join(a for a in paper.get("authors", []) if a)
        writer.writerow([
            paper.get("title", ""),
            authors_str,
            paper.get("published", ""),
            paper.get("summary", ""),
            paper.get("abs_link", ""),
            paper.get("pdf_link", ""),
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=arxiv_results.csv"},
    )


# ── Semantic Scholar routes ───────────────────────────────────────────────────

@literature_bp.route("/semantic", methods=["GET", "POST"])
def semantic():
    if request.method == "POST":
        raw_keywords = request.form.get("keywords", "")
        max_results  = int(request.form.get("max_results", 10))
        keywords     = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]

        try:
            papers = semantic_search(keywords, max_results=max_results)
            error  = None
        except Exception as e:
            papers = []
            error  = str(e)

        return render_template(
            "literature/semantic_scholar.html",
            papers=papers, last_query=raw_keywords,
            max_results=max_results, searched=True, error=error,
        )

    return render_template(
        "literature/semantic_scholar.html",
        papers=[], last_query="", max_results=10, searched=False, error=None,
    )


@literature_bp.route("/semantic/export", methods=["POST"])
def semantic_export():
    papers = _read_papers(SEMANTIC_RESULTS_FILE)
    output = io.StringIO()
    output.write('﻿')
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Year", "Citations", "Abstract", "Page", "PDF"])
    for paper in papers:
        authors_str = ", ".join(a for a in paper.get("authors", []) if a)
        writer.writerow([
            paper.get("title", ""), authors_str,
            paper.get("year", ""), paper.get("citations", ""),
            paper.get("abstract", ""), paper.get("url", ""), paper.get("pdf_url", ""),
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=semantic_results.csv"},
    )


# ── OpenAlex routes ───────────────────────────────────────────────────────────

@literature_bp.route("/openalex", methods=["GET", "POST"])
def openalex():
    if request.method == "POST":
        raw_keywords = request.form.get("keywords", "")
        max_results  = int(request.form.get("max_results", 10))
        keywords     = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]
        from_year    = request.form.get("from_year", "").strip()
        to_year      = request.form.get("to_year",   "").strip()
        from_year    = int(from_year) if from_year.isdigit() else None
        to_year      = int(to_year)   if to_year.isdigit()   else None

        papers = openalex_search(keywords, max_results=max_results,
                                 from_year=from_year, to_year=to_year)
        return render_template(
            "literature/openalex.html",
            papers=papers, last_query=raw_keywords,
            max_results=max_results,
            from_year=from_year or "", to_year=to_year or "",
            searched=True,
        )

    return render_template(
        "literature/openalex.html",
        papers=[], last_query="", max_results=10,
        from_year="", to_year="", searched=False,
    )


@literature_bp.route("/openalex/export", methods=["POST"])
def openalex_export():
    papers = _read_papers(OPENALEX_RESULTS_FILE)
    output = io.StringIO()
    output.write('﻿')
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Year", "Citations", "Abstract", "DOI", "Page", "PDF"])
    for paper in papers:
        writer.writerow([
            paper.get("title", ""), ", ".join(paper.get("authors", [])),
            paper.get("year", ""), paper.get("citations", ""),
            paper.get("abstract", ""), paper.get("doi", ""),
            paper.get("url", ""), paper.get("pdf_url", ""),
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=openalex_results.csv"},
    )


# ── IEEE routes ───────────────────────────────────────────────────────────────

@literature_bp.route("/ieee", methods=["GET", "POST"])
def ieee():
    api_key_set = bool(os.environ.get("IEEE_API_KEY", ""))

    if request.method == "POST" and api_key_set:
        raw_keywords = request.form.get("keywords", "")
        max_results  = int(request.form.get("max_results", 10))
        keywords     = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]
        from_year    = request.form.get("from_year", "").strip()
        to_year      = request.form.get("to_year",   "").strip()
        from_year    = int(from_year) if from_year.isdigit() else None
        to_year      = int(to_year)   if to_year.isdigit()   else None

        try:
            papers = ieee_search(keywords, max_results=max_results,
                                 from_year=from_year, to_year=to_year)
            return render_template(
                "literature/ieee.html",
                papers=papers, last_query=raw_keywords, max_results=max_results,
                from_year=from_year or "", to_year=to_year or "",
                api_key_set=api_key_set, searched=True,
            )
        except Exception as e:
            return render_template(
                "literature/ieee.html",
                papers=[], last_query=raw_keywords, max_results=max_results,
                from_year=from_year or "", to_year=to_year or "",
                api_key_set=api_key_set, searched=True, error=str(e),
            )

    return render_template(
        "literature/ieee.html",
        papers=[], last_query="", max_results=10,
        from_year="", to_year="",
        api_key_set=api_key_set, searched=False,
    )


@literature_bp.route("/ieee/export", methods=["POST"])
def ieee_export():
    papers = _read_papers(IEEE_RESULTS_FILE)
    output = io.StringIO()
    output.write('﻿')
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Year", "Citations", "Publication", "Abstract", "DOI", "Page", "PDF"])
    for paper in papers:
        writer.writerow([
            paper.get("title", ""), ", ".join(paper.get("authors", [])),
            paper.get("year", ""), paper.get("citations", ""),
            paper.get("publication", ""), paper.get("abstract", ""),
            paper.get("doi", ""), paper.get("url", ""), paper.get("pdf_url", ""),
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ieee_results.csv"},
    )


# ── Merge & Deduplicate routes ────────────────────────────────────────────────

@literature_bp.route("/merge", methods=["GET", "POST"])
def merge():
    source_counts  = {}
    source_queries = {}
    for source, filepath in SOURCE_FILES.items():
        papers, meta = _read_source_file(filepath)
        source_counts[source]  = len(papers)
        source_queries[source] = meta

    result = None
    if request.method == "POST":
        include_previous = "include_previous" in request.form
        result = merge_all(include_previous=include_previous)

    return render_template(
        "literature/merge.html",
        source_counts=source_counts,
        source_queries=source_queries,
        result=result,
    )


@literature_bp.route("/merge/export", methods=["POST"])
def merge_export():
    papers = []
    if os.path.exists(MERGED_FILE):
        with open(MERGED_FILE, encoding="utf-8") as f:
            papers = json.load(f)

    output = io.StringIO()
    output.write('﻿')
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Year", "Citations", "Abstract", "DOI", "Sources"])
    for paper in papers:
        year     = paper.get("year") or (paper.get("published") or "")[:4]
        abstract = paper.get("abstract") or paper.get("summary") or ""
        sources  = paper.get("_sources") or [paper.get("_source", "")]
        writer.writerow([
            paper.get("title", ""),
            ", ".join(a for a in paper.get("authors", []) if a),
            year, paper.get("citations", ""), abstract,
            paper.get("doi", ""),
            ", ".join(s for s in sources if s),
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=merged_results.csv"},
    )


# ── Lit Review Assistant routes ───────────────────────────────────────────────

@literature_bp.route("/litreview", methods=["GET"])
def litreview():
    """Renders the Lit Review page. Analysis is handled via the /litreview/stream SSE endpoint."""
    ollama_online    = False
    available_models = ["qwen3.5:0.8b"]
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        available_models = [m["name"] for m in r.json().get("models", [])]
        ollama_online = True
    except Exception:
        pass

    return render_template(
        "literature/lit_review.html",
        available_models=available_models,
        ollama_online=ollama_online,
    )


@literature_bp.route("/litreview/stream")
def litreview_stream():
    """
    Streams the LLM response token by token using Server-Sent Events (SSE).
    SSE keeps the HTTP connection open so the browser receives tokens in real time.
    """
    source     = request.args.get("source", "semantic")
    task       = request.args.get("task", "themes")
    model      = request.args.get("model", "qwen3.5:0.8b")
    max_papers = int(request.args.get("max_papers", 10))

    papers = load_papers(source)[:max_papers]
    prompt = build_prompt(papers, task)

    def generate():
        try:
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model":    model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_MESSAGE},
                        {"role": "user",   "content": prompt},
                    ],
                    "stream": True,
                },
                stream=True,
                timeout=300,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                data  = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    yield f"data: {json.dumps(token)}\n\n"
                if data.get("done"):
                    yield "data: [DONE]\n\n"
                    break
        except Exception as e:
            yield f"data: {json.dumps(f'Error: {e}')}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@literature_bp.route("/litreview/render", methods=["POST"])
def litreview_render():
    """Converts raw markdown text from the browser to HTML and returns it."""
    raw  = request.json.get("text", "")
    html = md_lib.markdown(raw, extensions=["tables"])
    return jsonify({"html": html})


# ── Problem Map routes ────────────────────────────────────────────────────────

@literature_bp.route("/problemmap", methods=["GET"])
def problemmap():
    ollama_online    = False
    available_models = ["qwen3.5:0.8b"]
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        available_models = [m["name"] for m in r.json().get("models", [])]
        ollama_online = True
    except Exception:
        pass

    previous = load_problem_map()
    return render_template(
        "literature/problem_map.html",
        available_models=available_models,
        ollama_online=ollama_online,
        previous=previous,
    )


@literature_bp.route("/problemmap/stream")
def problemmap_stream():
    model      = request.args.get("model", "qwen3.5:0.8b")
    batch_size = int(request.args.get("batch_size", 20))

    def generate():
        try:
            for event in extract_problems_stream(model=model, batch_size=batch_size):
                yield f"data: {event}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@literature_bp.route("/problemmap/export", methods=["POST"])
def problemmap_export():
    data        = load_problem_map()
    extractions = data.get("extractions", [])
    output      = io.StringIO()
    output.write('﻿')
    writer = csv.writer(output)
    writer.writerow(["Title", "Problem Solved", "Target System", "Solution Approach", "Claimed Benefit"])
    for e in extractions:
        writer.writerow([
            e.get("title", ""), e.get("problem_solved", ""),
            e.get("target_system", ""), e.get("solution_approach", ""),
            e.get("claimed_benefit", ""),
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=problem_map.csv"},
    )
