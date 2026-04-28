# problem_map_bot.py — Problem Map extraction pipeline.
#
# For each paper in the corpus, extracts what problem it solves,
# what system it targets, and what approach it uses.
# Aggregates results into frequency tables showing recurring research problems.

import json
import re
import requests
from datetime import datetime

from core.config import MERGED_FILE, PROBLEM_MAP_FILE
import os

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_MESSAGE = (
    "You are a research extraction assistant. "
    "You output ONLY valid JSON. No prose, no markdown, no explanation. "
    "If a field cannot be determined from the abstract, use the string \"not stated\"."
)

EXTRACTION_PROMPT = """\
For each paper below, extract four fields. Return ONLY a valid JSON array — \
no text before or after it.

Papers:
{paper_block}

Return a JSON array like this (one object per paper, in the same order):
[
  {{
    "title": "exact title from the paper list",
    "problem_solved": "one sentence: the specific problem this paper addresses",
    "target_system": "the robot, vehicle, or application this applies to (e.g. mobile robot, autonomous vehicle, drone, warehouse robot)",
    "solution_approach": "the core method proposed (e.g. DBSCAN clustering, graph SLAM, neural network)",
    "claimed_benefit": "the improvement claimed (e.g. higher accuracy, lower compute, better generalisation)"
  }}
]
"""


def _read_merged_papers() -> list[dict]:
    """Load papers from merged_results.json (handles both flat and wrapped formats)."""
    if not os.path.exists(MERGED_FILE):
        return []
    with open(MERGED_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("papers", [])


def _build_batch_prompt(batch: list[dict]) -> str:
    """Format a batch of papers into the extraction prompt."""
    paper_block = ""
    for i, p in enumerate(batch, 1):
        title    = p.get("title", "Untitled")
        abstract = (p.get("abstract") or p.get("summary") or "No abstract.")[:300]
        abstract = abstract.replace("\n", " ")
        paper_block += f"[{i}] {title}\n{abstract}\n\n"
    return EXTRACTION_PROMPT.format(paper_block=paper_block.strip())


def _call_ollama(model: str, prompt: str) -> str:
    """Send a prompt to Ollama and return the response text."""
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model":    model,
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user",   "content": prompt},
            ],
            "stream": False,
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _parse_json_response(text: str) -> list[dict]:
    """
    Extract a JSON array from the LLM response.
    Small models sometimes add text before or after the JSON — we strip it.
    Returns empty list on failure rather than crashing.
    """
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    match = re.search(r'\[.*?\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


def extract_problems_stream(
    model:      str = "qwen3.5:0.8b",
    batch_size: int = 20,
):
    """
    Generator — yields JSON progress events for SSE streaming.
    Each event is a JSON string:
      {"type": "progress", "batch": 3, "total": 18, "extracted": 60}
      {"type": "done", "result": {...}}
      {"type": "error", "message": "..."}
    """
    papers = _read_merged_papers()
    if not papers:
        yield json.dumps({"type": "error", "message": "No merged results found."})
        return

    batches     = [papers[i:i+batch_size] for i in range(0, len(papers), batch_size)]
    extractions = []
    errors      = 0

    for i, batch in enumerate(batches):
        yield json.dumps({
            "type":      "progress",
            "batch":     i + 1,
            "total":     len(batches),
            "extracted": len(extractions),
            "papers":    len(papers),
        })

        prompt = _build_batch_prompt(batch)
        try:
            response_text = _call_ollama(model, prompt)
            parsed = _parse_json_response(response_text)
            if parsed:
                extractions.extend(parsed)
            else:
                errors += len(batch)
                for p in batch:
                    extractions.append({
                        "title":             p.get("title", ""),
                        "problem_solved":    "extraction failed",
                        "target_system":     "extraction failed",
                        "solution_approach": "extraction failed",
                        "claimed_benefit":   "extraction failed",
                    })
        except Exception as e:
            errors += len(batch)
            yield json.dumps({"type": "batch_error", "batch": i + 1, "message": str(e)})

    aggregated = _aggregate(extractions)

    result = {
        "timestamp":    datetime.now().isoformat(timespec="seconds"),
        "model":        model,
        "total_papers": len(papers),
        "extracted":    len(extractions),
        "errors":       errors,
        "extractions":  extractions,
        "aggregated":   aggregated,
    }

    with open(PROBLEM_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    yield json.dumps({"type": "done", "result": result})


def _aggregate(extractions: list[dict]) -> dict:
    """Count problem and target system frequencies across all extracted papers."""
    from collections import Counter

    problem_words  = Counter()
    system_words   = Counter()
    approach_words = Counter()

    PROBLEM_KEYWORDS = [
        "mapping", "localisation", "localization", "slam", "obstacle detection",
        "path planning", "navigation", "perception", "segmentation", "clustering",
        "tracking", "odometry", "loop closure", "place recognition",
        "real-time", "accuracy", "robustness", "efficiency", "noise", "denoising",
        "dynamic environment", "occlusion", "multi-robot", "outdoor", "indoor",
    ]

    SYSTEM_KEYWORDS = [
        "mobile robot", "autonomous vehicle", "drone", "uav", "warehouse robot",
        "agricultural robot", "service robot", "humanoid", "arm", "manipulator",
        "car", "vehicle", "robot cleaner", "delivery robot", "ground vehicle",
        "quadruped", "legged robot",
    ]

    for entry in extractions:
        problem  = (entry.get("problem_solved") or "").lower()
        system   = (entry.get("target_system") or "").lower()
        approach = (entry.get("solution_approach") or "").lower()

        if "extraction failed" in problem:
            continue

        for kw in PROBLEM_KEYWORDS:
            if kw in problem:
                problem_words[kw] += 1

        for kw in SYSTEM_KEYWORDS:
            if kw in system:
                system_words[kw] += 1

        for method in ["dbscan", "slam", "neural", "deep learning", "lidar",
                        "point cloud", "graph", "kalman", "particle filter",
                        "imu", "camera", "fusion", "transformer"]:
            if method in approach:
                approach_words[method] += 1

    return {
        "top_problems":   problem_words.most_common(15),
        "top_systems":    system_words.most_common(10),
        "top_approaches": approach_words.most_common(10),
    }


def load_problem_map() -> dict:
    """Load the last saved problem map from disk."""
    if not os.path.exists(PROBLEM_MAP_FILE):
        return {}
    with open(PROBLEM_MAP_FILE, encoding="utf-8") as f:
        return json.load(f)
