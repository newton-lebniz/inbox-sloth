"""Talking to the local model. Everything goes through one tiny interface so
tests can swap in a fake and the model can be swapped by changing one env var."""
from __future__ import annotations

import json
from typing import Any, Dict, Protocol

import httpx

from . import config


class LLMError(Exception):
    pass


class LLM(Protocol):
    def analyze(self, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Return a JSON object that follows `schema`."""
        ...


class OllamaLLM:
    """Gemma (or any model) served by Ollama, using JSON-schema constrained output."""

    def __init__(self, url: str = config.OLLAMA_URL, model: str = config.MODEL,
                 timeout: float = config.LLM_TIMEOUT_S):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def analyze(self, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,           # structured outputs: the model must follow the schema
            "keep_alive": "30m",        # keep the model loaded between emails
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            r = httpx.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            r.raise_for_status()
            content = r.json()["message"]["content"]
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed: {e}") from e
        except (KeyError, ValueError) as e:
            raise LLMError(f"Unexpected Ollama response: {e}") from e
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Model did not return valid JSON: {content[:200]!r}") from e

    def health(self) -> Dict[str, Any]:
        """Is Ollama reachable, and is our model pulled?"""
        try:
            r = httpx.get(f"{self.url}/api/tags", timeout=5)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except httpx.HTTPError as e:
            return {"ok": False, "model": self.model, "error": f"Cannot reach Ollama at {self.url}: {e}"}
        wanted = self.model if ":" in self.model else self.model + ":latest"
        found = wanted in names
        return {
            "ok": found,
            "model": self.model,
            "error": None if found else f"Model not pulled. Run: ollama pull {self.model}",
            "available": names,
        }
