# merge_bot.py — Merges and deduplicates results from all search sources.

import json
import re

from core.config import (
    RESULTS_FILE,
    SEMANTIC_RESULTS_FILE,
    IEEE_RESULTS_FILE,
    OPENALEX_RESULTS_FILE,
    MERGED_FILE,
)
import os

# Input files — one per search source (all paths from core.config)
SOURCE_FILES = {
    "arxiv":     RESULTS_FILE,
    "semantic":  SEMANTIC_RESULTS_FILE,
    "ieee":      IEEE_RESULTS_FILE,
    "openalex":  OPENALEX_RESULTS_FILE,
}


def _read_source_file(filepath: str) -> tuple[list, dict]:
    """
    Load a source results file and return (papers, query_meta).
    Handles both file formats:
    - Old format: plain JSON array  [ {...}, {...} ]
    - New format: wrapped object    { "_query": {...}, "papers": [...] }
    Returns an empty list and empty dict if the file doesn't exist.
    """
    if not os.path.exists(filepath):
        return [], {}
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, {}
    return data.get("papers", []), data.get("_query", {})


def _normalize_title(title: str) -> str:
    """
    Reduce a title to a comparable form for duplicate detection.
    Example: "A Real-Time SLAM System!" → "a realtime slam system"
    """
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
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
        before processing new source files. Lets you accumulate papers across
        multiple searches without losing earlier results.

    Deduplication priority:
    1. DOI match — most reliable
    2. Normalised title match — catches papers without DOIs
    """
    seen_dois   = {}
    seen_titles = {}
    unique      = []
    previous_count = 0

    if include_previous and os.path.exists(MERGED_FILE):
        with open(MERGED_FILE, encoding="utf-8") as f:
            existing = json.load(f)
        previous_count = len(existing)
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

    raw_new    = []
    counts     = {}
    query_meta = {}

    for source, filepath in SOURCE_FILES.items():
        papers, meta = _read_source_file(filepath)
        counts[source]     = len(papers)
        query_meta[source] = meta
        for p in papers:
            p["_source"] = source
        raw_new.extend(papers)

    if not raw_new and not unique:
        return {"error": "No search results found. Run at least one search first."}

    total_before = previous_count + len(raw_new)

    for paper in raw_new:
        doi   = _normalize_doi(paper.get("doi", ""))
        title = _normalize_title(paper.get("title", ""))

        if doi and doi in seen_dois:
            _merge_into(unique[seen_dois[doi]], paper)
            continue
        if title and title in seen_titles:
            _merge_into(unique[seen_titles[title]], paper)
            continue

        idx = len(unique)
        unique.append(dict(paper))
        if doi:
            seen_dois[doi] = idx
        if title:
            seen_titles[title] = idx

    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    duplicates_removed = total_before - len(unique)
    print(f"[Merge Bot] {total_before} total → {len(unique)} unique "
          f"({duplicates_removed} duplicates removed)")

    return {
        "counts":             counts,
        "query_meta":         query_meta,
        "previous_count":     previous_count,
        "total_before":       total_before,
        "total_after":        len(unique),
        "duplicates_removed": duplicates_removed,
        "papers":             unique,
    }


def _merge_into(existing: dict, duplicate: dict):
    """
    When two records represent the same paper, keep the best data from each.
    - Abstract: keep the longer one
    - Citations: keep the higher number
    - Sources: record both origins
    """
    if len(duplicate.get("abstract", "") or duplicate.get("summary", "")) > \
       len(existing.get("abstract", "")  or existing.get("summary", "")):
        existing["abstract"] = duplicate.get("abstract") or duplicate.get("summary", "")

    existing_cites  = existing.get("citations", 0)  or 0
    duplicate_cites = duplicate.get("citations", 0) or 0
    existing["citations"] = max(existing_cites, duplicate_cites)

    sources = existing.get("_sources", [existing.get("_source", "unknown")])
    sources.append(duplicate.get("_source", "unknown"))
    existing["_sources"] = list(set(sources))
