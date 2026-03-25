# openalex_bot.py — OpenAlex academic search.
# OpenAlex is a fully open, free academic database with no API key required.
# Covers 250M+ works across all disciplines.
# Docs: https://docs.openalex.org

import os
import json
import requests
from datetime import datetime
from urllib.parse import urlencode

OPENALEX_BASE = "https://api.openalex.org/works"
RESULTS_FILE  = os.path.join(os.path.dirname(__file__), "..", "openalex_results.json")

# Adding an email enables the "polite pool" — higher rate limits, priority access.
# Set OPENALEX_EMAIL in your .env file. Works fine without it but slower under load.
MAILTO = os.environ.get("OPENALEX_EMAIL", "")


def _reconstruct_abstract(inverted_index: dict) -> str:
    """
    OpenAlex stores abstracts as an inverted index:
    { "word": [position1, position2], ... }

    This function reconstructs the original sentence by sorting words by position.
    Example: {"SLAM": [0], "is": [1], "hard": [2]} → "SLAM is hard"
    """
    if not inverted_index:
        return ""
    positions = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions.keys()))


def search(
    keywords:    list[str],
    max_results: int = 10,
    from_year:   int = None,
    to_year:     int = None,
) -> list[dict]:
    """
    Search OpenAlex for papers matching the given keywords.
    Returns a list of paper metadata dicts, sorted by citation count.
    No API key required.
    """
    query = " ".join(keywords)

    params = {
        "search":   query,
        "per_page": min(max_results, 200),   # OpenAlex max per page is 200
        "sort":     "cited_by_count:desc",   # most cited first
    }

    # Year range filter — OpenAlex uses filter=publication_year:YYYY-YYYY
    if from_year and to_year:
        params["filter"] = f"publication_year:{from_year}-{to_year}"
    elif from_year:
        params["filter"] = f"publication_year:>{from_year - 1}"
    elif to_year:
        params["filter"] = f"publication_year:<{to_year + 1}"

    # Polite pool — better rate limits when an email is provided
    if MAILTO:
        params["mailto"] = MAILTO

    # Select only the fields we need — keeps response small and fast
    params["select"] = (
        "id,title,authorships,publication_year,abstract_inverted_index,"
        "cited_by_count,doi,primary_location,open_access"
    )

    url = OPENALEX_BASE + "?" + urlencode(params)
    print(f"[OpenAlex Bot] Querying: {url}")

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    works = data.get("results", [])
    if not works:
        print("[OpenAlex Bot] No results found.")
        return []

    results = []
    for work in works:
        # Extract authors
        authors = [
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author")
        ]

        # Reconstruct abstract from inverted index
        abstract = _reconstruct_abstract(
            work.get("abstract_inverted_index") or {}
        )

        # Get page URL and PDF URL
        location = work.get("primary_location") or {}
        page_url = location.get("landing_page_url", "")
        pdf_url  = location.get("pdf_url", "") or \
                   (work.get("open_access") or {}).get("oa_url", "")

        # Clean DOI
        doi = work.get("doi", "") or ""
        doi = doi.replace("https://doi.org/", "")

        # OpenAlex ID is a URL — extract just the ID part for display
        oa_id = work.get("id", "").replace("https://openalex.org/", "")

        results.append({
            "id":        oa_id,
            "title":     work.get("title", "No title") or "No title",
            "authors":   authors,
            "year":      str(work.get("publication_year", "")),
            "abstract":  abstract,
            "citations": work.get("cited_by_count", 0),
            "doi":       doi,
            "url":       page_url or work.get("id", ""),
            "pdf_url":   pdf_url,
        })

    # Wrap results with query metadata so we always know what search produced this file
    wrapper = {
        "_query": {
            "keywords":    keywords,
            "from_year":   from_year,
            "to_year":     to_year,
            "max_results": max_results,
            "source":      "openalex",
            "timestamp":   datetime.now().isoformat(timespec="seconds"),
        },
        "papers": results,
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(wrapper, f, indent=2, ensure_ascii=False)

    print(f"[OpenAlex Bot] Found {len(results)} papers.")
    return results
