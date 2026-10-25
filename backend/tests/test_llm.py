import httpx

from app import llm as llm_mod
from app.llm import OllamaLLM, wsl_host_candidates


def test_explicit_url_is_never_second_guessed(monkeypatch):
    monkeypatch.setattr(llm_mod, "_reachable", lambda url: (_ for _ in ()).throw(AssertionError("probed")))
    m = OllamaLLM(url="http://example:1234/")
    m._ensure_url()
    assert m.url == "http://example:1234"


def test_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://172.30.96.1:11434")
    monkeypatch.setattr(llm_mod, "_reachable", lambda url: (_ for _ in ()).throw(AssertionError("probed")))
    m = OllamaLLM()
    m._ensure_url()
    assert m._probed


def test_falls_back_to_the_windows_host_under_wsl(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.setattr(llm_mod, "wsl_host_candidates", lambda: ["172.30.96.1", "10.255.255.254"])
    monkeypatch.setattr(llm_mod, "_reachable", lambda url: url == "http://172.30.96.1:11434")
    m = OllamaLLM()
    m._ensure_url()
    assert m.url == "http://172.30.96.1:11434"


def test_localhost_wins_when_it_works(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.setattr(llm_mod, "wsl_host_candidates", lambda: ["172.30.96.1"])
    monkeypatch.setattr(llm_mod, "_reachable", lambda url: True)
    m = OllamaLLM()
    m._ensure_url()
    assert m.url == "http://localhost:11434"


def test_health_reports_unreachable_ollama(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.setattr(llm_mod, "wsl_host_candidates", lambda: [])
    monkeypatch.setattr(llm_mod, "_reachable", lambda url: False)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    h = OllamaLLM().health()
    assert h["ok"] is False and "Cannot reach Ollama" in h["error"]


def test_wsl_candidates_parse_real_proc_files(monkeypatch, tmp_path):
    import pathlib
    files = {
        "/proc/version": "Linux version 5.15 (microsoft-standard-WSL2)",
        "/proc/net/route": "Iface Destination Gateway Flags\neth0\t00000000\t01601EAC\t0003\neth0\t00601EAC\t00000000\t0001",
        "/etc/resolv.conf": "# generated\nnameserver 10.255.255.254\n",
    }
    real = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: files[str(self)] if str(self) in files else real(self, *a, **k))
    # default gateway 01601EAC (little-endian hex) = 172.30.96.1, then the resolv.conf nameserver
    assert wsl_host_candidates() == ["172.30.96.1", "10.255.255.254"]
