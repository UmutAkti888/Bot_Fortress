# merge_bot.py — Merges and deduplicates results from all search sources.
# Combines ArXiv, Semantic Scholar, and IEEE Xplore results into a single
# unified list, removing duplicate papers that appear across sources.

import os
import json
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Input files — one per search source
SOURCE_FILES = {
    "arxiv":    os.path.join(REPO_ROOT, "results.json"),
    "semantic": os.path.join(REPO_ROOT, "semantic_results.json"),
    "ieee":     os.path.join(REPO_ROOT, "ieee_results.json"),
}

# Output file — the merged, deduplicated result
MERGED_FILE = os.path.join(REPO_ROOT, "merged_results.json")


def _normalize_title(title: str) -> str:
    """
    Reduce a title to a comparable form for duplicate detection.
    Lowercases, strips punctuation and extra whitespace.
    Example: "A Real-Time SLAM System!" → "a realtime slam system"
    """
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", "", title)  # remove punctuation
    title = re.sub(r"\s+", " ", title).strip()  # collapse whitespace
    return title


def _normalize_doi(doi: str) -> str:
    """Strip URL prefixes so '10.1109/...' and 'https://doi.org/10.1109/...' match."""
    doi = doi.lower().strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi


def merge_all() -> dict:
    """
    Load results from all available source files, deduplicate, and save.

    Deduplication priority:
    1. DOI match — most reliable (same paper, different sources)
    2. Normalised title match — catches papers without DOIs

    For duplicates, the version with the most information is kept
    (longest abstract wins; citation count takes the maximum).

    Returns a summary dict with counts for display in the UI.
    """
    raw_papers = []   # all papers before dedup, tagged with source
    counts     = {}   # how many came from each source

    for source, filepath in SOURCE_FILES.items():
        if not os.path.exists(filepath):
            counts[source] = 0
            continue
        with open(filepath, encoding="utf-8") as f:
            papers = json.load(f)
        counts[source] = len(papers)
        for p in papers:
            p["_source"] = source   # tag so we know where it came from
        raw_papers.extend(papers)

    if not raw_papers:
        return {"error": "No search results found. Run at least one search first."}

    # ── Deduplication ──────────────────────────────────────────────────────────
    seen_dois    = {}   # normalised DOI → index in `unique`
    seen_titles  = {}   # normalised title → index in `unique`
    unique       = []

    for paper in raw_papers:
        doi   = _normalize_doi(paper.get("doi", ""))
        title = _normalize_title(paper.get("title", ""))

        # Check if we've seen this DOI before
        if doi and doi in seen_dois:
            idx = seen_dois[doi]
            _merge_into(unique[idx], paper)
            continue

        # Check if we've seen this title before
        if title and title in seen_titles:
            idx = seen_titles[title]
            _merge_into(unique[idx], paper)
            continue

        # New paper — add to unique list
        idx = len(unique)
        unique.append(dict(paper))   # copy so we don't mutate the original
        if doi:
            seen_dois[doi] = idx
        if title:
            seen_titles[title] = idx

    # ── Save merged results ────────────────────────────────────────────────────
    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    duplicates_removed = len(raw_papers) - len(unique)

    print(f"[Merge Bot] {len(raw_papers)} total → {len(unique)} unique "
          f"({duplicates_removed} duplicates removed)")

    return {
        "counts":            counts,
        "total_before":      len(raw_papers),
        "total_after":       len(unique),
        "duplicates_removed": duplicates_removed,
        "papers":            unique,
    }


def _merge_into(existing: dict, duplicate: dict):
    """
    When two records represent the same paper, keep the best data from each.
    - Abstract: keep the longer one
    - Citations: keep the higher number
    - Sources: record both origins
    """
    # Keep longer abstract
    if len(duplicate.get("abstract", "") or duplicate.get("summary", "")) > \
       len(existing.get("abstract", "")  or existing.get("summary", "")):
        existing["abstract"] = duplicate.get("abstract") or duplicate.get("summary", "")

    # Keep higher citation count
    existing_cites  = existing.get("citations", 0)  or 0
    duplicate_cites = duplicate.get("citations", 0) or 0
    existing["citations"] = max(existing_cites, duplicate_cites)

    # Track all sources this paper was found in
    sources = existing.get("_sources", [existing.get("_source", "unknown")])
    sources.append(duplicate.get("_source", "unknown"))
    existing["_sources"] = list(set(sources))
