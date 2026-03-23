# semantic_scholar_bot.py — Semantic Scholar paper search logic.
# Uses the free Semantic Scholar Graph API (no API key required).
# Key advantage over ArXiv: returns citation counts, enabling relevance ranking.

import os
import json
import requests
from urllib.parse import urlencode

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "..", "semantic_results.json")

# Fields we request from the API — each one costs a bit of response size,
# so we only ask for what we actually use.
FIELDS = "title,authors,year,abstract,citationCount,externalIds,openAccessPdf,url"


def search(keywords: list[str], max_results: int = 10) -> list[dict]:
    """
    Search Semantic Scholar for papers matching the given keywords.
    Results are sorted by citation count (highest first) — most impactful papers first.
    Returns metadata only — does NOT download PDFs.
    """

    # Semantic Scholar uses plain space-separated terms, not AND logic.
    # This gives broader, relevance-ranked results compared to ArXiv's strict AND.
    query = " ".join(keywords)

    params = {
        "query":  query,
        "limit":  min(max_results, 100),  # API hard cap is 100 per request
        "fields": FIELDS,
    }
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params)

    print(f"[S2 Bot] Querying: {url}")

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[S2 Bot] Request failed: {e}")
        return []

    data = response.json()
    papers_raw = data.get("data", [])

    if not papers_raw:
        print("[S2 Bot] No results found.")
        return []

    results = []
    for paper in papers_raw:
        # Try to get a PDF link — prefer open access PDF, fall back to ArXiv if available
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

    # Sort by citation count — most cited papers appear first
    results.sort(key=lambda p: p["citations"], reverse=True)

    # Save metadata to JSON
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[S2 Bot] Found {len(results)} papers. Top citation count: {results[0]['citations']}")
    return results
