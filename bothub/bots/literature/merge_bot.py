# merge_bot.py — Merges and deduplicates results from all search sources.

import json
import re

from core.config import (
    RESULTS_FILE,
    SEMANTIC_RESULTS_FILE,
    IEEE_RESULTS_FILE,
    OPENALEX_RESULTS_FILE,
    MERGED_FILE,
    DEDUP_METRICS_LOG,
)
import os
import json as _json
from datetime import datetime

# How many past runs to average when judging whether this run's dedup rate
# looks implausible. Small window = reacts quickly to recent behavior.
_ROLLING_WINDOW = 10

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


def _paper_year(paper: dict) -> str:
    """
    Extract a 4-digit publication year as a string, or "" if unknown.
    Handles both the 'year' field (semantic/ieee/openalex) and the ArXiv
    'published' date (YYYY-MM-DD), from which the leading 4 digits are taken.
    """
    year = str(paper.get("year") or "").strip()
    if not year:
        year = str(paper.get("published") or "").strip()
    m = re.search(r"\d{4}", year)
    return m.group(0) if m else ""


def _first_author_surname(paper: dict) -> str:
    """
    Return the lowercased surname of the first listed author, or "" if none.
    Surname = last whitespace-separated token, stripped of punctuation, so
    'W. Hess' and 'Wolfgang Hess' both reduce to 'hess'.
    """
    authors = paper.get("authors") or []
    if not authors or not authors[0]:
        return ""
    tokens = str(authors[0]).strip().split()
    if not tokens:
        return ""
    surname = tokens[-1].lower()
    return re.sub(r"[^a-z0-9]", "", surname)


def _secondary_signal_matches(a: dict, b: dict) -> bool:
    """
    Confirm a title-only match with a second piece of evidence.
    Used ONLY when neither paper has a DOI, to stop two different papers that
    share a generic title (e.g. two different 'Introduction to Robotics') from
    being merged.

    Policy (chosen for this project): merge if the publication YEARS match OR
    the first-author SURNAMES match. Either signal is enough; both absent means
    we do not merge.
    """
    year_a, year_b = _paper_year(a), _paper_year(b)
    if year_a and year_b and year_a == year_b:
        return True

    surname_a, surname_b = _first_author_surname(a), _first_author_surname(b)
    if surname_a and surname_b and surname_a == surname_b:
        return True

    return False


def is_duplicate(a: dict, b: dict) -> bool:
    """
    Return True if papers `a` and `b` are considered the same work.

    Decision order:
      1. DOI evidence (strongest).
           - Both have a DOI and they are equal      -> duplicate.
           - Both have a DOI and they DIFFER          -> NOT a duplicate.
             A differing DOI is hard proof they are distinct works, so it
             VETOES the title fallback below (this is what stops two different
             papers that share a generic title from merging).
      2. Title fallback (when DOI could not decide — i.e. at least one side
         has no DOI).
           - Titles must be present and normalized-equal, AND
           - a secondary signal must agree: matching publication YEAR OR
             matching first-author SURNAME.
             This is required for EVERY title-only match, including the
             preprint-vs-published case (one side has a DOI, the other does
             not). A shared generic title is not enough on its own — two
             different 'Deep Learning' papers must not merge just because one
             of them happens to carry a DOI. Real cross-source duplicates
             reliably share an author or a year, so this does not cost us
             legitimate merges.

    Pure function (no file or global state) so the rule is testable pair by
    pair. tests/test_dedup.py exercises this directly, and merge_all() routes
    its title-fallback decision through it so there is a single source of truth.
    """
    doi_a = _normalize_doi(a.get("doi") or "")
    doi_b = _normalize_doi(b.get("doi") or "")

    # ── DOI evidence ──────────────────────────────────────────────────────────
    if doi_a and doi_b:
        return doi_a == doi_b          # equal -> dup; differ -> distinct (veto)

    # ── Title fallback (at least one side has no DOI) ─────────────────────────
    title_a = _normalize_title(a.get("title") or "")
    title_b = _normalize_title(b.get("title") or "")
    if not (title_a and title_b and title_a == title_b):
        return False

    # A matching title alone is too weak for generic titles — require a
    # secondary signal (matching year OR matching first-author surname).
    return _secondary_signal_matches(a, b)


# ── Dedup observability (Step 3 — runtime paper trail, not a UI) ──────────────

def _read_recent_metrics(window: int = _ROLLING_WINDOW) -> list[dict]:
    """
    Return up to the last `window` metric records from the JSON-lines log.
    Silently returns [] if the log is missing or any line is unreadable —
    observability must never break the merge itself.
    """
    if not os.path.exists(DEDUP_METRICS_LOG):
        return []
    records = []
    try:
        with open(DEDUP_METRICS_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(_json.loads(line))
                except ValueError:
                    continue  # skip a corrupt line rather than abort
    except OSError:
        return []
    return records[-window:]


def _log_metrics(metrics: dict) -> None:
    """Append one metrics record as a JSON line. Best-effort — never raises."""
    try:
        with open(DEDUP_METRICS_LOG, "a", encoding="utf-8") as f:
            f.write(_json.dumps(metrics, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[Merge Bot] Could not write dedup metrics log: {e}")


def _check_dedup_health(metrics: dict, history: list[dict]) -> list[str]:
    """
    Compare this run's dedup rate against the rolling average of prior runs
    and return a list of human-readable warnings (empty if all looks normal).

    Two implausibility signals:
      1. Dedup rate collapsed to 0% on a run where cross-source overlap was
         plausible (multiple sources returned papers) — suggests the matcher
         silently stopped matching.
      2. Dedup rate deviates sharply (> 40 percentage points) from the rolling
         average of recent runs — a spike or crash worth a second look.
    """
    warnings = []
    rate = metrics["dedup_rate"]

    # Signal 1: zero dedup despite multiple sources contributing papers.
    active_sources = sum(1 for v in metrics["source_counts"].values() if v > 0)
    if rate == 0.0 and active_sources >= 2 and metrics["total_before"] > 1:
        warnings.append(
            f"dedup rate is 0% across {active_sources} active sources "
            f"({metrics['total_before']} papers) — matcher may have stopped working."
        )

    # Signal 2: sharp deviation from the rolling average of prior runs.
    prior_rates = [h["dedup_rate"] for h in history if "dedup_rate" in h]
    if len(prior_rates) >= 3:
        avg = sum(prior_rates) / len(prior_rates)
        if abs(rate - avg) > 0.40:
            warnings.append(
                f"dedup rate {rate:.0%} deviates sharply from recent average "
                f"{avg:.0%} (last {len(prior_rates)} runs)."
            )

    return warnings


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

    # ── Observability counters (do NOT affect the dedup decision) ─────────────
    incoming_with_doi = 0   # incoming records that carried a usable DOI
    merged_via_doi    = 0   # merges resolved on the DOI path
    merged_via_title  = 0   # merges resolved on the title fallback

    for paper in raw_new:
        doi   = _normalize_doi(paper.get("doi", ""))
        title = _normalize_title(paper.get("title", ""))

        if doi:
            incoming_with_doi += 1

        # Fast DOI path: an equal DOI is always a duplicate.
        if doi and doi in seen_dois:
            merged_via_doi += 1
            _merge_into(unique[seen_dois[doi]], paper)
            continue

        # Title candidate: confirm with is_duplicate() before merging. This is
        # what applies the DOI veto (differing DOIs block a title merge) and the
        # secondary-signal requirement for DOI-less pairs. A title collision
        # that is NOT a real duplicate falls through and is kept as a new paper.
        if title and title in seen_titles:
            candidate = unique[seen_titles[title]]
            if is_duplicate(paper, candidate):
                merged_via_title += 1
                _merge_into(candidate, paper)
                continue

        idx = len(unique)
        unique.append(dict(paper))
        if doi:
            seen_dois[doi] = idx
        # Only claim the title bucket if it is unused, so the first paper under
        # a shared title remains the comparison anchor for later candidates.
        if title and title not in seen_titles:
            seen_titles[title] = idx

    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    duplicates_removed = total_before - len(unique)
    print(f"[Merge Bot] {total_before} total -> {len(unique)} unique "
          f"({duplicates_removed} duplicates removed)")

    # ── Emit the runtime paper trail (Step 3) ─────────────────────────────────
    # doi_coverage: of the NEW incoming records, how many had a DOI at all.
    # A low value means dedup is leaning on the fragile title fallback.
    new_count    = len(raw_new)
    doi_coverage = (incoming_with_doi / new_count) if new_count else 0.0
    dedup_rate   = (duplicates_removed / total_before) if total_before else 0.0

    metrics = {
        "timestamp":        datetime.now().isoformat(timespec="seconds"),
        "source_counts":    counts,
        "total_before":     total_before,
        "total_after":      len(unique),
        "duplicates_removed": duplicates_removed,
        "dedup_rate":       round(dedup_rate, 4),
        "incoming_new":     new_count,
        "incoming_with_doi": incoming_with_doi,
        "doi_coverage":     round(doi_coverage, 4),
        "merged_via_doi":   merged_via_doi,
        "merged_via_title": merged_via_title,
    }

    # Compare against recent history BEFORE appending this run.
    history  = _read_recent_metrics()
    warnings = _check_dedup_health(metrics, history)
    metrics["warnings"] = warnings

    print(f"[Merge Bot] DOI coverage {doi_coverage:.0%} of {new_count} new "
          f"| dedup rate {dedup_rate:.0%} "
          f"| merges: {merged_via_doi} by DOI, {merged_via_title} by title")
    for w in warnings:
        print(f"[Merge Bot] WARNING: {w}")

    _log_metrics(metrics)

    return {
        "counts":             counts,
        "query_meta":         query_meta,
        "previous_count":     previous_count,
        "total_before":       total_before,
        "total_after":        len(unique),
        "duplicates_removed": duplicates_removed,
        "dedup_rate":         round(dedup_rate, 4),
        "doi_coverage":       round(doi_coverage, 4),
        "merged_via_doi":     merged_via_doi,
        "merged_via_title":   merged_via_title,
        "warnings":           warnings,
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
