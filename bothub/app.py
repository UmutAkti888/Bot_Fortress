# app.py — Flask entry point.

import sys
import csv
import io
import json
import os
import requests
from flask import Flask, render_template, request, Response, stream_with_context, jsonify
import markdown as md_lib

# Add the repo root (Bot_Fortress/) to Python's search path.
# This lets us import from the top-level bots/ package, which lives outside bothub/.
# Without this, Python would only look inside bothub/ and not find bots/.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from bots.arxiv_bot import search, download_pdfs
from bots.semantic_scholar_bot import search as semantic_search
from bots.lit_review_bot import load_papers, build_prompt, SYSTEM_MESSAGE
from bots.ieee_bot import search as ieee_search
from bots.merge_bot import merge_all
from bots.openalex_bot import search as openalex_search

# Load .env file if present (IEEE_API_KEY etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except ImportError:
    pass  # python-dotenv not installed — keys must be set as system env vars

SEMANTIC_RESULTS_FILE = os.path.join(REPO_ROOT, "semantic_results.json")

# results.json now lives at repo root alongside bots/ and papers/
RESULTS_FILE = os.path.join(REPO_ROOT, "results.json")

app = Flask(__name__)


def _read_papers(filepath: str) -> list:
    """
    Load papers from a results JSON file, handling both formats:
    - Old flat format:  [ {...}, {...} ]            (plain array)
    - New wrapped format: { "_query": {...}, "papers": [...] }

    Returns an empty list if the file doesn't exist.
    This helper is used by all export and download routes so that the
    query-metadata change doesn't break existing functionality.
    """
    if not os.path.exists(filepath):
        return []
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data              # old format
    return data.get("papers", [])  # new wrapped format


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/arxiv", methods=["GET", "POST"])
def arxiv():
    if request.method == "POST":
        raw_keywords = request.form.get("keywords", "")
        max_results  = int(request.form.get("max_results", 10))
        keywords     = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]

        # Year filter — empty string means "no filter", so we convert to int or None
        from_year = request.form.get("from_year", "").strip()
        to_year   = request.form.get("to_year",   "").strip()
        from_year = int(from_year) if from_year.isdigit() else None
        to_year   = int(to_year)   if to_year.isdigit()   else None

        # search() only hits the API — no PDF downloading, so it's fast.
        papers = search(keywords, max_results=max_results, from_year=from_year, to_year=to_year)

        return render_template(
            "arxiv.html",
            papers=papers,
            last_query=raw_keywords,
            max_results=max_results,
            from_year=from_year or "",
            to_year=to_year or "",
            searched=True,
        )

    return render_template(
        "arxiv.html",
        papers=[], last_query="", max_results=10,
        from_year="", to_year="", searched=False,
    )


@app.route("/arxiv/download", methods=["POST"])
def arxiv_download():
    """
    Triggered by the 'Download PDFs' button.
    Reads the last search results from results.json and downloads all PDFs.
    Runs synchronously — may take a while for large result sets.
    """
    papers = _read_papers(RESULTS_FILE)
    downloaded = download_pdfs(papers)

    # Read back the hidden fields the form sent us, so the page re-renders correctly
    last_query  = request.form.get("last_query",  "")
    max_results = int(request.form.get("max_results", 10))
    from_year   = request.form.get("from_year", "")
    to_year     = request.form.get("to_year",   "")

    return render_template(
        "arxiv.html",
        papers=papers,
        last_query=last_query,
        max_results=max_results,
        from_year=from_year,
        to_year=to_year,
        searched=True,
        download_status=f"Downloaded {len(downloaded)} PDF(s) to the papers/ folder.",
    )


@app.route("/arxiv/export", methods=["POST"])
def arxiv_export():
    """
    Triggered by the 'Export to CSV' button.
    Reads the last search results from results.json and returns a CSV file download.
    Uses only Python stdlib — no extra libraries needed.
    """
    papers = _read_papers(RESULTS_FILE)

    # io.StringIO() creates an in-memory text buffer — like a file, but in RAM.
    # This avoids writing a temporary file to disk just to send it to the browser.
    output = io.StringIO()

    # Write a UTF-8 BOM (Byte Order Mark) as the very first character.
    # Excel uses this hidden marker to detect that the file is UTF-8 encoded.
    # Without it, Excel guesses Windows-1252 and corrupts accented characters.
    output.write('\ufeff')

    writer = csv.writer(output)

    # Header row
    writer.writerow(["Title", "Authors", "Published", "Abstract", "ArXiv Link", "PDF Link"])

    for paper in papers:
        # Filter out None entries — feedparser occasionally returns None for
        # author names on malformed ArXiv entries, which breaks str.join().
        authors_str = ", ".join(a for a in paper.get("authors", []) if a)
        writer.writerow([
            paper.get("title", ""),
            authors_str,
            paper.get("published", ""),
            paper.get("summary", ""),
            paper.get("abs_link", ""),
            paper.get("pdf_link", ""),
        ])

    output.seek(0)  # Rewind the buffer to the start before reading

    # Response() lets us return raw data with custom headers.
    # Content-Disposition: attachment tells the browser to download it, not display it.
    # The filename shown in the Save dialog will be "arxiv_results.csv".
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=arxiv_results.csv"}
    )


@app.route("/semantic", methods=["GET", "POST"])
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
            "semantic_scholar.html",
            papers=papers,
            last_query=raw_keywords,
            max_results=max_results,
            searched=True,
            error=error,
        )

    return render_template(
        "semantic_scholar.html",
        papers=[], last_query="", max_results=10, searched=False, error=None,
    )


@app.route("/semantic/export", methods=["POST"])
def semantic_export():
    """Export last Semantic Scholar results as a CSV file."""
    papers = _read_papers(SEMANTIC_RESULTS_FILE)

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel
    writer = csv.writer(output)

    writer.writerow(["Title", "Authors", "Year", "Citations", "Abstract", "Page", "PDF"])

    for paper in papers:
        authors_str = ", ".join(a for a in paper.get("authors", []) if a)
        writer.writerow([
            paper.get("title", ""),
            authors_str,
            paper.get("year", ""),
            paper.get("citations", ""),
            paper.get("abstract", ""),
            paper.get("url", ""),
            paper.get("pdf_url", ""),
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=semantic_results.csv"}
    )


@app.route("/openalex", methods=["GET", "POST"])
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
            "openalex.html",
            papers=papers, last_query=raw_keywords,
            max_results=max_results,
            from_year=from_year or "", to_year=to_year or "",
            searched=True,
        )

    return render_template(
        "openalex.html",
        papers=[], last_query="", max_results=10,
        from_year="", to_year="", searched=False,
    )


@app.route("/openalex/export", methods=["POST"])
def openalex_export():
    openalex_file = os.path.join(REPO_ROOT, "openalex_results.json")
    papers = _read_papers(openalex_file)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Year", "Citations", "Abstract", "DOI", "Page", "PDF"])
    for paper in papers:
        writer.writerow([
            paper["title"], ", ".join(paper["authors"]), paper["year"],
            paper["citations"], paper["abstract"],
            paper["doi"], paper["url"], paper["pdf_url"],
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=openalex_results.csv"}
    )


@app.route("/merge", methods=["GET", "POST"])
def merge():
    """
    Merge & Deduplicate page.
    GET  — shows current source counts, no merge yet.
    POST — triggers the merge and shows results.
    """
    from bots.merge_bot import SOURCE_FILES, _read_source_file

    # Read each source file — handles both old (plain array) and new (wrapped) formats.
    # We collect paper counts AND the last query metadata for display.
    source_counts = {}
    source_queries = {}   # last _query block per source, shown under each count
    for source, filepath in SOURCE_FILES.items():
        papers, meta = _read_source_file(filepath)
        source_counts[source]  = len(papers)
        source_queries[source] = meta   # {} if file missing or old format

    result = None
    if request.method == "POST":
        # If the "accumulate" checkbox is ticked, keep existing merged papers
        # as the base and add new results on top (cross-query accumulation).
        include_previous = "include_previous" in request.form
        result = merge_all(include_previous=include_previous)

    return render_template(
        "merge.html",
        source_counts=source_counts,
        source_queries=source_queries,
        result=result,
    )


@app.route("/merge/export", methods=["POST"])
def merge_export():
    """
    Export the merged, deduplicated results as a clean CSV file.
    Strips internal fields (_source, _sources, abs_link, pdf_link, etc.)
    so the file is compact and readable when fed to an LLM like Claude.
    Columns: Title, Authors, Year, Citations, Abstract, DOI, Sources
    """
    merged_file = os.path.join(REPO_ROOT, "merged_results.json")
    papers = []
    if os.path.exists(merged_file):
        with open(merged_file, encoding="utf-8") as f:
            papers = json.load(f)

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel
    writer = csv.writer(output)

    writer.writerow(["Title", "Authors", "Year", "Citations", "Abstract", "DOI", "Sources"])

    for paper in papers:
        # Year: ArXiv stores "published" (e.g. "2023-01-15"), others store "year" (int)
        year = paper.get("year") or (paper.get("published") or "")[:4]

        # Abstract: ArXiv calls it "summary", all others call it "abstract"
        abstract = paper.get("abstract") or paper.get("summary") or ""

        # Sources: after merging, duplicates gain a "_sources" list; single-source
        # papers only have "_source". We normalise to a readable string either way.
        sources_list = paper.get("_sources") or [paper.get("_source", "")]
        sources_str  = ", ".join(s for s in sources_list if s)

        authors_str = ", ".join(a for a in paper.get("authors", []) if a)
        writer.writerow([
            paper.get("title", ""),
            authors_str,
            year,
            paper.get("citations", ""),
            abstract,
            paper.get("doi", ""),
            sources_str,
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=merged_results.csv"}
    )


@app.route("/ieee", methods=["GET", "POST"])
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
                "ieee.html",
                papers=papers, last_query=raw_keywords,
                max_results=max_results,
                from_year=from_year or "", to_year=to_year or "",
                api_key_set=api_key_set, searched=True,
            )
        except Exception as e:
            return render_template(
                "ieee.html",
                papers=[], last_query=raw_keywords, max_results=max_results,
                from_year=from_year or "", to_year=to_year or "",
                api_key_set=api_key_set, searched=True, error=str(e),
            )

    return render_template(
        "ieee.html",
        papers=[], last_query="", max_results=10,
        from_year="", to_year="",
        api_key_set=api_key_set, searched=False,
    )


@app.route("/ieee/export", methods=["POST"])
def ieee_export():
    """Export last IEEE Xplore results as a CSV file."""
    ieee_results_file = os.path.join(REPO_ROOT, "ieee_results.json")
    papers = _read_papers(ieee_results_file)

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["Title", "Authors", "Year", "Citations", "Publication", "Abstract", "DOI", "Page", "PDF"])
    for paper in papers:
        writer.writerow([
            paper["title"], ", ".join(paper["authors"]), paper["year"],
            paper["citations"], paper["publication"], paper["abstract"],
            paper["doi"], paper["url"], paper["pdf_url"],
        ])
    output.seek(0)
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ieee_results.csv"}
    )


@app.route("/litreview", methods=["GET"])
def litreview():
    """
    Renders the Literature Review Assistant page.
    Analysis is handled entirely via the /litreview/stream SSE endpoint,
    triggered by JavaScript — this route only serves the page.
    """
    # Ask Ollama which models are installed — populates the model dropdown.
    # If Ollama isn't running we fall back to a sensible default list.
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        available_models = [m["name"] for m in r.json().get("models", [])]
        ollama_online = True
    except Exception:
        available_models = ["qwen3.5:0.8b"]
        ollama_online = False

    return render_template(
        "lit_review.html",
        available_models=available_models,
        ollama_online=ollama_online,
    )


@app.route("/litreview/stream")
def litreview_stream():
    """
    Streams the LLM response token by token using Server-Sent Events (SSE).
    SSE is a browser standard: the server keeps the connection open and pushes
    small chunks of text. The browser receives them in real time — no page reload.
    This eliminates the timeout problem entirely: tokens flow as soon as they're ready.
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
                    "stream":   True,   # Ollama sends one JSON line per token
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
                    # SSE format: each message is "data: <payload>\n\n"
                    # We JSON-encode the token so special characters are safe to transmit
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
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # Disables proxy buffering — needed for SSE to work
        },
    )


@app.route("/litreview/render", methods=["POST"])
def litreview_render():
    """
    Receives raw markdown text from the browser (sent as JSON after streaming ends).
    Converts it to HTML using Python's markdown library and returns it.
    The browser then injects the HTML directly into the result div.
    'tables' extension enables markdown table support — the LLM uses these often.
    """
    raw = request.json.get("text", "")
    html = md_lib.markdown(raw, extensions=["tables"])
    return jsonify({"html": html})


if __name__ == "__main__":
    app.run(debug=True)
