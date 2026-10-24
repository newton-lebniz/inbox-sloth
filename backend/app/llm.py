"""Talking to the local model. Everything goes through one tiny interface so
tests can swap in a fake and the model can be swapped by changing one env var."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import httpx

from . import config


class LLMError(Exception):
    pass


class LLM(Protocol):
    def analyze(self, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Return a JSON object that follows `schema`."""
        ...


def wsl_host_candidates() -> List[str]:
    """Inside WSL2, Ollama running on Windows is not at localhost. Likely addresses of the
    Windows host: the default gateway, then the nameserver in resolv.conf."""
    try:
        if "microsoft" not in Path("/proc/version").read_text().lower():
            return []
    except OSError:
        return []
    found: List[str] = []
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000":          # default route
                found.append(".".join(str(int(f[2][i:i + 2], 16)) for i in (6, 4, 2, 0)))
                break
    except (OSError, ValueError):
        pass
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            if line.startswith("nameserver"):
                found.append(line.split()[1])
                break
    except (OSError, IndexError):
        pass
    return list(dict.fromkeys(found))


def _reachable(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/tags", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


class OllamaLLM:
    """Gemma (or any model) served by Ollama, using JSON-schema constrained output."""

    def __init__(self, url: Optional[str] = None, model: str = config.MODEL,
                 timeout: float = config.LLM_TIMEOUT_S):
        # An explicit url (argument or OLLAMA_URL) is always respected; otherwise localhost is
        # tried first and, under WSL2, the Windows host is tried if localhost has no Ollama.
        self._probed = url is not None or "OLLAMA_URL" in os.environ
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        self.model = model
        self.timeout = timeout

    def _ensure_url(self) -> None:
        if self._probed:
            return
        self._probed = True
        if _reachable(self.url):
            return
        for host in wsl_host_candidates():
            candidate = f"http://{host}:11434"
            if _reachable(candidate):
                self.url = candidate
                return

    def analyze(self, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_url()
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
        self._ensure_url()
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
