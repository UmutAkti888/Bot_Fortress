"""
tests/test_dedup.py — Safety net for AcademiBot's cross-source deduplication.

WHAT THIS DOES
  Loads the known-pairs test set (dedup_test_cases.json) and runs every pair
  through merge_bot.is_duplicate() — the pure predicate that mirrors the
  deduplication decision inside merge_all().

  For each pair in "should_dedupe"     → is_duplicate() must return True.
  For each pair in "should_not_dedupe" → is_duplicate() must return False.

  Results are reported as a PASS-RATE PERCENTAGE (not just pass/fail) so that
  a future change to the dedup logic that degrades accuracy is visible even
  if it doesn't break everything at once.

HOW TO RUN
  From the bothub/ directory:
      python tests/test_dedup.py
  Or from the repo root:
      python bothub/tests/test_dedup.py

  No pytest required. It is also pytest-compatible: `pytest tests/test_dedup.py`
  will collect test_should_dedupe / test_should_not_dedupe.

EXIT CODE
  0  if every case matches its expected outcome (100%).
  1  if any case disagrees — used so this can gate commits later (see Step 5
     in the module CLAUDE.md).

  NOTE: the CURRENT dedup logic is expected to FAIL a few "should_not_dedupe"
  cases — these are documented false positives (identical generic titles with
  differing/absent DOIs). That is intentional: this test set exists to make
  that weakness measurable before it is fixed.
"""

import json
import os
import sys

# Put bothub/ on the path so `from bots.literature...` resolves regardless of
# where the test is launched from (repo root or bothub/).
_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BOTHUB_DIR = os.path.dirname(_THIS_DIR)
if _BOTHUB_DIR not in sys.path:
    sys.path.insert(0, _BOTHUB_DIR)

from bots.literature.merge_bot import is_duplicate  # noqa: E402

_CASES_FILE = os.path.join(_THIS_DIR, "dedup_test_cases.json")


def _load_cases() -> dict:
    with open(_CASES_FILE, encoding="utf-8") as f:
        return json.load(f)


def evaluate() -> dict:
    """
    Run every pair and collect results.
    Returns a summary dict with per-case outcomes and an overall pass rate.
    """
    cases = _load_cases()
    results = []

    for pair in cases.get("should_dedupe", []):
        got = is_duplicate(pair["a"], pair["b"])
        results.append({
            "group":    "should_dedupe",
            "expected": True,
            "got":      got,
            "ok":       got is True,
            "reason":   pair.get("reason", ""),
        })

    for pair in cases.get("should_not_dedupe", []):
        got = is_duplicate(pair["a"], pair["b"])
        results.append({
            "group":    "should_not_dedupe",
            "expected": False,
            "got":      got,
            "ok":       got is False,
            "reason":   pair.get("reason", ""),
        })

    passed = sum(1 for r in results if r["ok"])
    total  = len(results)
    rate   = (passed / total * 100.0) if total else 0.0

    return {
        "results": results,
        "passed":  passed,
        "total":   total,
        "rate":    rate,
    }


def _print_report(summary: dict) -> None:
    print("=" * 74)
    print("AcademiBot dedup - known-pairs test set")
    print("=" * 74)

    for i, r in enumerate(summary["results"], 1):
        mark = "PASS" if r["ok"] else "FAIL"
        exp  = "dupe" if r["expected"] else "distinct"
        got  = "dupe" if r["got"] else "distinct"
        print(f"[{mark}] #{i:02d} {r['group']:<17} expected={exp:<8} got={got}")
        if not r["ok"]:
            # Wrap the reason so failures are self-explanatory in the log
            print(f"        -> {r['reason']}")

    print("-" * 74)
    print(f"Pass rate: {summary['passed']}/{summary['total']} "
          f"= {summary['rate']:.1f}%")

    fails = [r for r in summary["results"] if not r["ok"]]
    if fails:
        print(f"\n{len(fails)} case(s) diverge from expected behavior.")
        print("These are the documented dedup weaknesses to address in Step 4.")
    else:
        print("\nAll cases match expected behavior. [OK]")
    print("=" * 74)


# ── pytest-compatible entry points ────────────────────────────────────────────

def test_should_dedupe():
    """Every should_dedupe pair must be detected as a duplicate."""
    cases = _load_cases()
    failures = [
        p["reason"] for p in cases["should_dedupe"]
        if not is_duplicate(p["a"], p["b"])
    ]
    assert not failures, f"{len(failures)} should-dedupe pairs missed: {failures}"


def test_should_not_dedupe():
    """Every should_not_dedupe pair must be kept distinct."""
    cases = _load_cases()
    failures = [
        p["reason"] for p in cases["should_not_dedupe"]
        if is_duplicate(p["a"], p["b"])
    ]
    assert not failures, f"{len(failures)} should-not-dedupe pairs wrongly merged: {failures}"


# ── standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    summary = evaluate()
    _print_report(summary)
    # Exit non-zero if anything diverges, so this can gate commits later.
    sys.exit(0 if summary["passed"] == summary["total"] else 1)
