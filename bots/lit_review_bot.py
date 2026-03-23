# lit_review_bot.py — Literature Review Assistant powered by a local Ollama model.
# Sends paper abstracts to a locally running LLM and returns structured analysis.
# No internet required — completely offline after papers are fetched.

import requests
import json
import os

# Ollama runs a local HTTP server on this address by default.
# It's the same pattern as ArXiv/Semantic Scholar — just a different host.
OLLAMA_URL = "http://localhost:11434/api/chat"

# Where the last search results live (repo root)
ARXIV_RESULTS    = os.path.join(os.path.dirname(__file__), "..", "results.json")
SEMANTIC_RESULTS = os.path.join(os.path.dirname(__file__), "..", "semantic_results.json")

# Available analysis tasks — shown as options in the UI
TASKS = {
    "themes":   "Identify the main research themes across these papers and explain how they relate to each other.",
    "priority": "Rank these papers by importance for a literature review. Explain why the top ones are critical to read.",
    "gaps":     "Based on these papers, identify research gaps and open questions the field has not addressed yet.",
    "summary":  "Write a one-sentence summary for each paper capturing its core contribution.",
    "critique": "Critically evaluate these papers. Which claims are well-supported? Which methodologies seem weak?",
}


def load_papers(source: str) -> list[dict]:
    """
    Load the last saved search results from disk.
    source: "arxiv" or "semantic"
    """
    path = ARXIV_RESULTS if source == "arxiv" else SEMANTIC_RESULTS
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_prompt(papers: list[dict], task: str) -> str:
    """
    Format the paper list into a prompt the LLM can work with.
    We include title, year, citation count (if available), and a truncated abstract.
    We cap the abstract at 400 characters to keep the total prompt manageable
    for smaller models like 0.8B.
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

    prompt = (
        f"You are a research assistant helping with an academic literature review.\n\n"
        f"Task: {task_instruction}\n\n"
        f"Papers:\n{paper_block}\n\n"
        f"Provide a clear, structured response."
    )
    return prompt


def analyze(
    papers:    list[dict],
    task:      str   = "themes",
    model:     str   = "qwen3.5:0.8b",
    max_papers: int  = 20,
) -> str:
    """
    Send papers to the local Ollama model and return the analysis text.

    max_papers: caps how many papers are sent in one request.
    Small models (0.8B) struggle beyond ~15-20 abstracts in one prompt.
    Use the 4B model for larger batches with better coherence.
    """
    # Take only the first N papers (already sorted by citation count for S2)
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
                "stream":   False,   # Wait for the full response before returning
            },
            timeout=180,  # Local LLMs can be slow — give them 3 minutes
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return "Could not connect to Ollama. Make sure Ollama is running (check your system tray)."
    except requests.exceptions.Timeout:
        return "Ollama timed out. Try fewer papers or a smaller model."
    except requests.exceptions.RequestException as e:
        return f"Request failed: {e}"

    result = response.json()
    return result["message"]["content"]
