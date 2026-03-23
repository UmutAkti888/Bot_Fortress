# app.py — Flask entry point.

import sys
import csv
import io
import json
import os
from flask import Flask, render_template, request, Response

# Add the repo root (Bot_Fortress/) to Python's search path.
# This lets us import from the top-level bots/ package, which lives outside bothub/.
# Without this, Python would only look inside bothub/ and not find bots/.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from bots.arxiv_bot import search, download_pdfs

# results.json now lives at repo root alongside bots/ and papers/
RESULTS_FILE = os.path.join(REPO_ROOT, "results.json")

app = Flask(__name__)


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
    papers = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, encoding="utf-8") as f:
            papers = json.load(f)

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
    papers = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, encoding="utf-8") as f:
            papers = json.load(f)

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
        writer.writerow([
            paper["title"],
            ", ".join(paper["authors"]),
            paper["published"],
            paper["summary"],
            paper["abs_link"],
            paper["pdf_link"],
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


if __name__ == "__main__":
    app.run(debug=True)
