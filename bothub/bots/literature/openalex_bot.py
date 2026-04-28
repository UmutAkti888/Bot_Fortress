# openalex_bot.py — OpenAlex academic search.
# OpenAlex is fully open and free — no API key required.
# Docs: https://docs.openalex.org

import os
import json
import requests
from datetime import datetime
from urllib.parse import urlencode

from core.config import OPENALEX_RESULTS_FILE

OPENALEX_BASE = "https://api.openalex.org/works"
MAILTO = os.environ.get("OPENALEX_EMAIL", "")


def _reconstruct_abstract(inverted_index: dict) -> str:
    """
    OpenAlex stores abstracts as an inverted index:
    { "word": [position1, position2], ... }
    This reconstructs the original sentence by sorting words by position.
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
    """
    query = " ".join(keywords)

    params = {
        "search":   query,
        "per_page": min(max_results, 200),
        "sort":     "cited_by_count:desc",
    }

    if from_year and to_year:
        params["filter"] = f"publication_year:{from_year}-{to_year}"
    elif from_year:
        params["filter"] = f"publication_year:>{from_year - 1}"
    elif to_year:
        params["filter"] = f"publication_year:<{to_year + 1}"

    if MAILTO:
        params["mailto"] = MAILTO

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
        authors = [
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author")
        ]
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index") or {})

        location = work.get("primary_location") or {}
        page_url = location.get("landing_page_url", "")
        pdf_url  = location.get("pdf_url", "") or \
                   (work.get("open_access") or {}).get("oa_url", "")

        doi = (work.get("doi", "") or "").replace("https://doi.org/", "")
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
    with open(OPENALEX_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(wrapper, f, indent=2, ensure_ascii=False)

    print(f"[OpenAlex Bot] Found {len(results)} papers.")
    return results
