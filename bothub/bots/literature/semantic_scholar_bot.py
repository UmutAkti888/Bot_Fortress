# semantic_scholar_bot.py — Semantic Scholar paper search logic.
# Uses the Semantic Scholar Graph API.
# A free API key is available at: https://www.semanticscholar.org/product/api
# Set SEMANTIC_API_KEY in your .env file for higher rate limits.

import os
import json
import requests
from datetime import datetime
from urllib.parse import urlencode

from core.config import SEMANTIC_RESULTS_FILE

# Optional API key — massively increases rate limits.
SEMANTIC_API_KEY = os.environ.get("SEMANTIC_API_KEY", "")

# Fields we request from the API — only what we actually use.
FIELDS = "title,authors,year,abstract,citationCount,externalIds,openAccessPdf,url"


def search(keywords: list[str], max_results: int = 10) -> list[dict]:
    """
    Search Semantic Scholar for papers matching the given keywords.
    Results are sorted by citation count (highest first).
    Raises RuntimeError on API errors so the UI can display them.
    """
    query = " ".join(keywords)

    params = {
        "query":  query,
        "limit":  min(max_results, 100),  # API hard cap is 100 per request
        "fields": FIELDS,
    }
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params)

    headers = {}
    if SEMANTIC_API_KEY:
        headers["x-api-key"] = SEMANTIC_API_KEY

    print(f"[S2 Bot] Querying: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting Semantic Scholar: {e}")

    if response.status_code == 429:
        raise RuntimeError(
            "Semantic Scholar rate limit reached (HTTP 429). "
            "Wait a minute and try again, or add a free SEMANTIC_API_KEY to your .env file."
        )
    if not response.ok:
        raise RuntimeError(
            f"Semantic Scholar API returned HTTP {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    papers_raw = data.get("data", [])

    if not papers_raw:
        print("[S2 Bot] No results found.")
        return []

    results = []
    for paper in papers_raw:
        arxiv_id  = paper.get("externalIds", {}).get("ArXiv", "")
        open_pdf  = paper.get("openAccessPdf") or {}
        pdf_url   = open_pdf.get("url", "")
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

        results.append({
            "id":        paper.get("paperId", ""),
            "title":     paper.get("title", "No title"),
            "authors":   [a["name"] for a in paper.get("authors", [])],
            "year":      str(paper.get("year") or ""),
            "abstract":  (paper.get("abstract") or "").replace("\n", " ").strip(),
            "citations": paper.get("citationCount", 0),
            "url":       paper.get("url", ""),
            "pdf_url":   pdf_url,
            "arxiv_id":  arxiv_id,
        })

    results.sort(key=lambda p: p["citations"], reverse=True)

    wrapper = {
        "_query": {
            "keywords":    keywords,
            "from_year":   None,
            "to_year":     None,
            "max_results": max_results,
            "source":      "semantic",
            "timestamp":   datetime.now().isoformat(timespec="seconds"),
        },
        "papers": results,
    }
    with open(SEMANTIC_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(wrapper, f, indent=2, ensure_ascii=False)

    print(f"[S2 Bot] Found {len(results)} papers.")
    return results
