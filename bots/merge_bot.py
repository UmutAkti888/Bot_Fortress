# merge_bot.py — Merges and deduplicates results from all search sources.
# Combines ArXiv, Semantic Scholar, and IEEE Xplore results into a single
# unified list, removing duplicate papers that appear across sources.

import os
import json
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Input files — one per search source
SOURCE_FILES = {
    "arxiv":     os.path.join(REPO_ROOT, "results.json"),
    "semantic":  os.path.join(REPO_ROOT, "semantic_results.json"),
    "ieee":      os.path.join(REPO_ROOT, "ieee_results.json"),
    "openalex":  os.path.join(REPO_ROOT, "openalex_results.json"),
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


def merge_all(include_previous=False) -> dict:
    """
    Load results from all available source files, deduplicate, and save.

    Parameters
    ----------
    include_previous : bool
        If True, load the existing merged_results.json as the starting base
        before processing new source files. This lets you accumulate papers
        across multiple searches — e.g. run query A, merge, then run query B
        and merge again without losing query A's results.

    Deduplication priority:
    1. DOI match — most reliable (same paper, different sources)
    2. Normalised title match — catches papers without DOIs

    For duplicates, the version with the most information is kept
    (longest abstract wins; citation count takes the maximum).

    Returns a summary dict with counts for display in the UI.
    """
    # ── Step 1: Build starting base ────────────────────────────────────────────
    # These lookup dicts map a normalised key → index in `unique`.
    seen_dois   = {}
    seen_titles = {}
    unique      = []
    previous_count = 0  # how many papers were already in the merged file

    if include_previous and os.path.exists(MERGED_FILE):
        with open(MERGED_FILE, encoding="utf-8") as f:
            existing = json.load(f)
        previous_count = len(existing)
        # Seed the dedup lookups with all previously merged papers
        for paper in existing:
            doi   = _normalize_doi(paper.get("doi", ""))
            title = _normalize_title(paper.get("title", ""))
            idx   = len(unique)
            unique.append(dict(paper))
            if doi:
                seen_dois[doi] = idx
            if title:
                seen_titles[title] = idx
        print(f"[Merge Bot] Loaded {previous_count} existing papers as base.")

    # ── Step 2: Load new results from each source file ─────────────────────────
    raw_new = []   # new papers from this search run (before dedup)
    counts  = {}   # papers per source, for the UI summary line

    for source, filepath in SOURCE_FILES.items():
        if not os.path.exists(filepath):
            counts[source] = 0
            continue
        with open(filepath, encoding="utf-8") as f:
            papers = json.load(f)
        counts[source] = len(papers)
        for p in papers:
            p["_source"] = source   # tag so we know where it came from
        raw_new.extend(papers)

    if not raw_new and not unique:
        return {"error": "No search results found. Run at least one search first."}

    # ── Step 3: Merge new papers into the base with deduplication ──────────────
    total_before = previous_count + len(raw_new)

    for paper in raw_new:
        doi   = _normalize_doi(paper.get("doi", ""))
        title = _normalize_title(paper.get("title", ""))

        # Check if we've seen this DOI before (in base or already processed)
        if doi and doi in seen_dois:
            _merge_into(unique[seen_dois[doi]], paper)
            continue

        # Check if we've seen this title before
        if title and title in seen_titles:
            _merge_into(unique[seen_titles[title]], paper)
            continue

        # Genuinely new paper — add to unique list
        idx = len(unique)
        unique.append(dict(paper))
        if doi:
            seen_dois[doi] = idx
        if title:
            seen_titles[title] = idx

    # ── Step 4: Save merged results ────────────────────────────────────────────
    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    duplicates_removed = total_before - len(unique)

    print(f"[Merge Bot] {total_before} total → {len(unique)} unique "
          f"({duplicates_removed} duplicates removed)")

    return {
        "counts":            counts,
        "previous_count":    previous_count,   # papers already in merged file
        "total_before":      total_before,
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
