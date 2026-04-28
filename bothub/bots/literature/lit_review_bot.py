# lit_review_bot.py — Literature Review Assistant powered by a local Ollama model.
# Sends paper abstracts to a locally running LLM and returns structured analysis.
# No internet required — completely offline after papers are fetched.

import requests
import json
import os

from core.config import (
    RESULTS_FILE     as ARXIV_RESULTS,
    SEMANTIC_RESULTS_FILE as SEMANTIC_RESULTS,
    IEEE_RESULTS_FILE     as IEEE_RESULTS,
    OPENALEX_RESULTS_FILE as OPENALEX_RESULTS,
    MERGED_FILE      as MERGED_RESULTS,
)

# Ollama runs a local HTTP server on this address by default.
OLLAMA_URL = "http://localhost:11434/api/chat"

# System message sent before every request — sets the model's behaviour globally.
SYSTEM_MESSAGE = (
    "You are a formal academic research assistant writing a literature review. "
    "Always respond with structured, direct analysis. "
    "Never begin with conversational phrases such as 'Of course', 'Certainly', "
    "'Sure', 'I have identified', 'Based on the provided', or similar openers. "
    "Start immediately with the analysis content. "
    "Use markdown formatting: headers (###), bullet points, bold for key terms, "
    "and tables where appropriate."
)

# Available analysis tasks — shown as options in the UI
TASKS = {
    "themes":   "Identify the main research themes across these papers. For each theme, explain what it covers and how it connects to the others.",
    "priority": "Rank these papers by importance for a literature review. For each, state why it is or is not critical to read.",
    "gaps":     "Identify research gaps and open questions across these papers. What problems remain unsolved? What directions are missing?",
    "summary":  "Write a one-sentence summary for each paper capturing its core contribution. Number each entry to match the paper list.",
    "critique": "Critically evaluate these papers. For each, assess whether the claims are well-supported and whether the methodology is sound.",
}


def _read_papers(filepath: str) -> list[dict]:
    """
    Load papers from a results JSON file.
    Handles both old (plain array) and new (wrapped) formats.
    """
    if not os.path.exists(filepath):
        return []
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("papers", [])


def load_papers(source: str) -> list[dict]:
    """
    Load the last saved search results from disk.
    source: "arxiv", "semantic", "ieee", "openalex", or "merged"
    """
    paths = {
        "arxiv":    ARXIV_RESULTS,
        "semantic": SEMANTIC_RESULTS,
        "ieee":     IEEE_RESULTS,
        "openalex": OPENALEX_RESULTS,
        "merged":   MERGED_RESULTS,
    }
    path = paths.get(source, SEMANTIC_RESULTS)
    return _read_papers(path)


def build_prompt(papers: list[dict], task: str) -> str:
    """
    Format the paper list into a prompt the LLM can work with.
    Includes title, year, citation count, and a truncated abstract.
    Abstract is capped at 400 characters to keep prompts manageable for small models.
    """
    task_instruction = TASKS.get(task, TASKS["themes"])

    paper_block = ""
    for i, p in enumerate(papers, 1):
        title     = p.get("title", "Untitled")
        year      = str(p.get("year", p.get("published", "")[:4]))
        abstract  = (p.get("abstract") or p.get("summary") or "No abstract available.")
        abstract  = abstract[:400].replace("\n", " ")
        citations = p.get("citations")
        cite_str  = f" | {citations} citations" if citations is not None else ""
        paper_block += f"\n[{i}] {title} ({year}{cite_str})\n{abstract}\n"

    return f"Task: {task_instruction}\n\nPapers:\n{paper_block}"


def analyze(
    papers:     list[dict],
    task:       str  = "themes",
    model:      str  = "qwen3.5:0.8b",
    max_papers: int  = 20,
) -> str:
    """
    Send papers to the local Ollama model and return the analysis text.
    max_papers caps how many papers are sent — small models struggle beyond ~20 abstracts.
    """
    papers = papers[:max_papers]
    if not papers:
        return "No papers to analyse. Run a search first."

    prompt = build_prompt(papers, task)
    print(f"[LitReview Bot] Sending {len(papers)} papers to {model}...")

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model":    model,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
            },
            timeout=180,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return "Could not connect to Ollama. Make sure Ollama is running."
    except requests.exceptions.Timeout:
        return "Ollama timed out. Try fewer papers or a smaller model."
    except requests.exceptions.RequestException as e:
        return f"Request failed: {e}"

    return response.json()["message"]["content"]
