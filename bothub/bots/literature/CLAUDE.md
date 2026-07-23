# CLAUDE.md — AcademiBot literature module

## Highest-risk module: deduplication (`merge_bot.py`)

`merge_bot.py` merges papers from ArXiv, Semantic Scholar, IEEE, and OpenAlex
and removes duplicates. It looks simple but fails **silently** on real edge
cases (missing DOIs, generic titles, formatting differences). A regression
here does not raise an error — it just quietly merges different papers or
splits the same paper, and nobody notices until the merged results are wrong.

### HARD STOP RULE

> **Any change to the dedup logic must pass `tests/test_dedup.py` before
> committing. Treat a failing test as a hard stop — not a warning to note and
> move past.**

Run it from the `bothub/` directory:

```bash
python tests/test_dedup.py
```

Exit code `0` means 13/13 pass. Any non-zero exit means you changed behavior
the test set pins down — stop and reconcile before committing. If a change is
*intentional*, update `tests/dedup_test_cases.json` in the same commit and say
why in the message; never edit a fixture just to make a red test go green.

### The dedup contract (what `is_duplicate(a, b)` guarantees)

1. **DOI evidence wins.** Both papers have a DOI and they are equal → duplicate.
   Both have a DOI and they **differ** → distinct (this *vetoes* any title
   match — a differing DOI is proof they are different works).
2. **Title fallback needs corroboration.** When at least one side has no DOI, a
   normalized-title match is accepted **only if** a secondary signal agrees:
   matching publication **year** OR matching **first-author surname**. A shared
   generic title alone ("A Survey of Deep Learning") is never enough.

`merge_all()` routes its title decision through `is_duplicate()`, so the live
pipeline and the tests share one source of truth. Keep it that way.

### Field-shape gotchas (why the rules look the way they do)

- **ArXiv** has **no DOI** and no `year` field — it carries `summary` (not
  `abstract`) and a `published` date (`YYYY-MM-DD`).
- **Semantic Scholar** does **not** expose a top-level `doi` (it sits unused in
  `externalIds`), so S2 papers also rely on the title fallback.
- Only **IEEE** and **OpenAlex** emit a `doi`. DOI-based matching therefore
  only fully works between those two sources; the other two depend on the
  title + secondary-signal path. If you ever start extracting DOIs for ArXiv
  or S2, add test cases for it.

### Observability

`merge_all()` writes a per-run record to `dedup_metrics.log` (repo root,
gitignored): DOI coverage, dedup rate, and merge-path breakdown. It logs a
`WARNING` when the dedup rate collapses to 0% across multiple active sources
or deviates sharply from the rolling average of recent runs. If you see those
warnings, investigate before trusting the merged output.
