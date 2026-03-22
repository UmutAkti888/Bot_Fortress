# arxiv_bot.py — ArXiv paper search and download logic.

import os
import json
import requests
import feedparser
from urllib.parse import urlencode  # Safely encodes special characters in URLs

PAPERS_DIR  = os.path.join(os.path.dirname(__file__), "..", "papers")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "..", "results.json")


def search(
    keywords: list[str],
    max_results: int = 10,
    from_year: int = None,
    to_year:   int = None,
) -> list[dict]:
    """
    Search ArXiv for papers matching the given keywords.
    Optionally filter by publication year range.
    Returns metadata only — does NOT download PDFs.
    Fast enough to use inside a web request.
    """

    # Join keywords into an ArXiv query string: all:SLAM AND all:mapping
    query = " AND ".join(f"all:{kw}" for kw in keywords)

    # Date range filter — ArXiv accepts: submittedDate:[YYYYMMDD TO YYYYMMDD]
    # If only one bound is given, we use a sensible default for the other.
    if from_year or to_year:
        from_date = f"{from_year if from_year else 1900}0101"
        to_date   = f"{to_year   if to_year   else 2099}1231"
        query += f" AND submittedDate:[{from_date} TO {to_date}]"

    # urlencode() handles spaces and special characters in the query string.
    # Without it, "mobile robot" becomes a broken URL with a raw space in it.
    params = {
        "search_query": query,
        "max_results":  max_results,
        "sortBy":       "submittedDate",
        "sortOrder":    "descending",
    }
    url = "http://export.arxiv.org/api/query?" + urlencode(params)

    print(f"[ArXiv Bot] Querying: {url}")
    feed = feedparser.parse(url)

    if not feed.entries:
        print("[ArXiv Bot] No results found.")
        return []

    results = []
    for entry in feed.entries:
        title     = entry.get("title", "No title").replace("\n", " ").strip()
        authors   = [a.name for a in entry.get("authors", [])]
        summary   = entry.get("summary", "").replace("\n", " ").strip()
        published = entry.get("published", "")[:10]
        abs_link  = entry.get("link", "")
        pdf_link  = abs_link.replace("/abs/", "/pdf/")
        paper_id  = abs_link.split("/")[-1]

        results.append({
            "id":        paper_id,
            "title":     title,
            "authors":   authors,
            "summary":   summary,
            "published": published,
            "abs_link":  abs_link,
            "pdf_link":  pdf_link,
        })

    # Save metadata to JSON so it persists between sessions
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[ArXiv Bot] Found {len(results)} papers.")
    return results


def download_pdfs(papers: list[dict]) -> list[str]:
    """
    Download PDFs for a list of papers (as returned by search()).
    Returns a list of filenames that were successfully downloaded.
    Intended for background/CLI use — can be slow for large result sets.
    """
    os.makedirs(PAPERS_DIR, exist_ok=True)
    downloaded = []

    for paper in papers:
        pdf_filename = f"{paper['id']}.pdf"
        pdf_path = os.path.join(PAPERS_DIR, pdf_filename)

        if os.path.exists(pdf_path):
            print(f"[ArXiv Bot] Already exists: {pdf_filename}")
            downloaded.append(pdf_filename)
            continue

        try:
            print(f"[ArXiv Bot] Downloading: {paper['title'][:60]}...")
            response = requests.get(paper["pdf_link"], timeout=20)
            response.raise_for_status()
            with open(pdf_path, "wb") as f:
                f.write(response.content)
            downloaded.append(pdf_filename)
            print(f"[ArXiv Bot] Saved: {pdf_filename}")
        except Exception as e:
            print(f"[ArXiv Bot] Failed: {pdf_filename} — {e}")

    return downloaded


def search_and_download(keywords: list[str], max_results: int = 10) -> list[dict]:
    """
    Convenience function for CLI use: search then immediately download all PDFs.
    """
    papers = search(keywords, max_results)
    if papers:
        download_pdfs(papers)
    return papers
