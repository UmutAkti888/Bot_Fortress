"""
core/ollama.py — Shared Ollama helpers used across all bot modules.

WHY THIS EXISTS:
Before restructuring, every route that needed to talk to Ollama had its
own inline call to localhost:11434. If the port or URL ever changed, every
file needed updating. Now it's one place.

WHAT IS OLLAMA:
Ollama is a local LLM server that listens on port 11434 by default.
We use two endpoints:
  - GET  /api/tags   → returns a list of installed models
  - POST /api/chat   → send a prompt, get a response (streaming or blocking)
"""

import requests

OLLAMA_BASE = "http://localhost:11434"


def check_status() -> bool:
    """
    Return True if Ollama is running and reachable.
    Used by bot pages to show the green/yellow status badge.
    """
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        return r.ok
    except Exception:
        return False


def get_models(fallback: list[str] = None) -> list[str]:
    """
    Return a list of installed model names (e.g. ["qwen3.5:0.8b", "llama3:4b"]).
    If Ollama is offline, returns `fallback` instead of crashing.
    The fallback defaults to a single safe model name.
    """
    if fallback is None:
        fallback = ["qwen3.5:0.8b"]
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return models if models else fallback
    except Exception:
        return fallback
