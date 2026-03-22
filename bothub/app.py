# app.py — Flask entry point.

import json
import os
from flask import Flask, render_template, request
from bots.arxiv_bot import search, download_pdfs

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "results.json")

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


if __name__ == "__main__":
    app.run(debug=True)
