# arxiv_bot.py — ArXiv paper search and download logic.
# This is pure Python. No Flask here — just a function we can call from anywhere.

import os
import json
import requests
import feedparser

# Where to save downloaded PDFs (relative to app.py, one level up from this file)
PAPERS_DIR = os.path.join(os.path.dirname(__file__), "..", "papers")

# Where to save the metadata JSON file
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "..", "results.json")


def search_and_download(keywords: list[str], max_results: int = 10) -> list[dict]:
    """
    Search ArXiv for papers matching the given keywords, download their PDFs,
    and save metadata to results.json.

    Args:
        keywords:    List of search terms, e.g. ["SLAM", "mobile robotics"]
        max_results: How many papers to fetch (default 10)

    Returns:
        A list of dicts, each containing metadata for one paper.
    """

    # --- STEP 1: BUILD THE QUERY URL ---
    # ArXiv uses a simple query string format.
    # "all:SLAM AND all:mapping" searches all fields for both terms.
    query = " AND ".join(f"all:{kw}" for kw in keywords)

    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query={query}"
        f"&max_results={max_results}"
        f"&sortBy=submittedDate"
        f"&sortOrder=descending"
    )

    # --- STEP 2: FETCH AND PARSE THE RESPONSE ---
    # feedparser handles the Atom XML format that ArXiv returns.
    # It gives us a clean Python object (feed.entries) instead of raw XML.
    print(f"[ArXiv Bot] Querying: {url}")
    feed = feedparser.parse(url)

    if not feed.entries:
        print("[ArXiv Bot] No results found.")
        return []

    # --- STEP 3: MAKE SURE THE PAPERS FOLDER EXISTS ---
    os.makedirs(PAPERS_DIR, exist_ok=True)

    results = []

    for entry in feed.entries:
        # Extract metadata from the parsed feed entry
        title   = entry.get("title", "No title").replace("\n", " ").strip()
        authors = [a.name for a in entry.get("authors", [])]
        summary = entry.get("summary", "").replace("\n", " ").strip()
        published = entry.get("published", "")[:10]  # Keep only the date part: YYYY-MM-DD

        # The entry link looks like: https://arxiv.org/abs/2301.12345
        # Replacing "abs" with "pdf" gives us the direct PDF link.
        abs_link = entry.get("link", "")
        pdf_link = abs_link.replace("/abs/", "/pdf/")

        # --- STEP 4: DOWNLOAD THE PDF ---
        paper_id = abs_link.split("/")[-1]  # e.g. "2301.12345"
        pdf_filename = f"{paper_id}.pdf"
        pdf_path = os.path.join(PAPERS_DIR, pdf_filename)

        downloaded = False
        if not os.path.exists(pdf_path):  # Skip if already downloaded
            try:
                print(f"[ArXiv Bot] Downloading: {title[:60]}...")
                response = requests.get(pdf_link, timeout=20)
                response.raise_for_status()  # Raises an error if download failed
                with open(pdf_path, "wb") as f:
                    f.write(response.content)
                downloaded = True
                print(f"[ArXiv Bot] Saved: {pdf_filename}")
            except Exception as e:
                print(f"[ArXiv Bot] Failed to download {pdf_filename}: {e}")
        else:
            downloaded = True
            print(f"[ArXiv Bot] Already exists, skipping: {pdf_filename}")

        # --- STEP 5: COLLECT METADATA ---
        results.append({
            "id":         paper_id,
            "title":      title,
            "authors":    authors,
            "summary":    summary,
            "published":  published,
            "abs_link":   abs_link,
            "pdf_link":   pdf_link,
            "pdf_file":   pdf_filename if downloaded else None,
        })

    # --- STEP 6: SAVE METADATA TO JSON ---
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[ArXiv Bot] Done. {len(results)} papers saved to results.json.")
    return results
