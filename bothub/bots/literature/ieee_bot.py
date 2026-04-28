# ieee_bot.py — IEEE Xplore metadata search.
# Uses the official IEEE Xplore API (requires a free API key from developer.ieee.org).

import os
import json
import requests
from datetime import datetime
from urllib.parse import urlencode

from core.config import IEEE_RESULTS_FILE

IEEE_API_KEY  = os.environ.get("IEEE_API_KEY", "")
IEEE_BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def search(
    keywords: list[str],
    max_results: int = 10,
    from_year: int = None,
    to_year: int = None,
) -> list[dict]:
    """
    Search IEEE Xplore for papers matching the given keywords.
    Raises RuntimeError if no API key is configured.
    """
    if not IEEE_API_KEY:
        raise RuntimeError(
            "IEEE_API_KEY is not set. Add it to your .env file: IEEE_API_KEY=your_key_here"
        )

    query = " ".join(keywords)

    params = {
        "apikey":      IEEE_API_KEY,
        "querytext":   query,
        "max_records": min(max_results, 200),
        "sort_field":  "article_number",
        "sort_order":  "desc",
    }
    if from_year:
        params["start_year"] = from_year
    if to_year:
        params["end_year"] = to_year

    url = IEEE_BASE_URL + "?" + urlencode(params)
    print(f"[IEEE Bot] Querying: {url}")

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    articles = data.get("articles", [])
    if not articles:
        print("[IEEE Bot] No results found.")
        return []

    results = []
    for article in articles:
        authors_data = article.get("authors", {}).get("authors", [])
        authors = [a.get("full_name", "") for a in authors_data]

        pdf_url = article.get("pdf_url", "")
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = "https://ieeexplore.ieee.org" + pdf_url

        results.append({
            "id":           str(article.get("article_number", "")),
            "title":        article.get("title", "No title"),
            "authors":      authors,
            "year":         str(article.get("publication_year", "")),
            "abstract":     article.get("abstract", ""),
            "citations":    article.get("citing_paper_count", 0),
            "doi":          article.get("doi", ""),
            "url":          article.get("html_url", ""),
            "pdf_url":      pdf_url,
            "publication":  article.get("publication_title", ""),
        })

    results.sort(key=lambda p: p["citations"], reverse=True)

    wrapper = {
        "_query": {
            "keywords":    keywords,
            "from_year":   from_year,
            "to_year":     to_year,
            "max_results": max_results,
            "source":      "ieee",
            "timestamp":   datetime.now().isoformat(timespec="seconds"),
        },
        "papers": results,
    }
    with open(IEEE_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(wrapper, f, indent=2, ensure_ascii=False)

    print(f"[IEEE Bot] Found {len(results)} papers.")
    return results
