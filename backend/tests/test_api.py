import pytest
from fastapi.testclient import TestClient

from app.db import Store
from app.main import create_app
from fake_model import FakeLLM


@pytest.fixture
def client():
    return TestClient(create_app(Store(":memory:"), FakeLLM()))


def test_health_and_profile_roundtrip(client):
    assert client.get("/api/health").json()["ok"] is True
    p = client.get("/api/profile").json()
    assert p["onboarded"] is False and p["role"] == "student"

    saved = client.put("/api/profile", json={
        "role": "freelancer", "priorities": ["invoices", "client replies"], "reminder_style": "last_minute",
    }).json()
    assert saved["onboarded"] is True
    assert client.get("/api/profile").json()["role"] == "freelancer"


def test_bad_profile_is_rejected(client):
    assert client.put("/api/profile", json={"role": "wizard"}).status_code == 422


def test_sample_load_process_and_list(client):
    assert client.post("/api/emails/sample").json() == {"added": 18, "total": 18}
    assert client.post("/api/emails/sample").json()["added"] == 0      # no duplicates

    status = client.post("/api/process?wait=true").json()
    assert status["state"] == "done" and status["done"] == 18 and status["errors"] == []

    tasks = client.get("/api/commitments").json()
    assert len(tasks) == 12
    dated = [t["due_at"] for t in tasks if t["due_at"]]
    assert dated == sorted(dated), "dated tasks come first, soonest first"
    assert tasks[-1]["due_at"] is None, "undated task goes last"


def test_source_email_and_history_are_available(client):
    client.post("/api/emails/sample")
    client.post("/api/process?wait=true")
    task = next(t for t in client.get("/api/commitments").json() if "probability" in t["title"].lower())
    detail = client.get(f"/api/commitments/{task['id']}").json()
    assert [e["event"] for e in detail["events"]] == ["created", "deadline_changed"]
    email = client.get(f"/api/emails/{detail['source_email_id']}").json()
    assert "Thursday 22 October" in email["body"]


def test_mark_done_and_filter(client):
    client.post("/api/emails/sample")
    client.post("/api/process?wait=true")
    first = client.get("/api/commitments").json()[0]
    assert client.patch(f"/api/commitments/{first['id']}", json={"status": "done"}).json()["status"] == "done"
    assert len(client.get("/api/commitments?status=pending").json()) == 11
    assert client.patch(f"/api/commitments/{first['id']}", json={"status": "nope"}).status_code == 422
    assert client.patch("/api/commitments/9999", json={"status": "done"}).status_code == 404


def test_import_custom_emails(client):
    r = client.post("/api/emails", json=[{
        "id": "x1", "from": "Boss <boss@work.example>", "subject": "Report",
        "body": "Please send the report by Friday.", "sent_at": "2026-10-19T09:00:00"}])
    assert r.json()["added"] == 1
    assert client.post("/api/emails", json=[{"id": "bad"}]).status_code == 422


def test_unknown_email_is_404_and_list_hides_bodies(client):
    assert client.get("/api/emails/nope").status_code == 404
    client.post("/api/emails/sample")
    assert "body" not in client.get("/api/emails").json()[0]


def test_skipped_items_are_exposed_with_reasons(client):
    from fake_model import SCRIPT, FakeLLM, task
    import copy
    script = copy.deepcopy(SCRIPT)
    script["Mess menu change this week"]["tasks"] = [task("Khichdi dinner", "Thursday", "Due to supply issues the Thursday dinner menu changes")]
    c = TestClient(create_app(Store(":memory:"), FakeLLM(script)))
    c.post("/api/emails/sample")
    c.post("/api/process?wait=true")
    skipped = c.get("/api/skipped").json()
    assert any(s["reason"] == "informational" and s["title"] == "Khichdi dinner" and s["subject"] for s in skipped)
    assert not [t for t in c.get("/api/commitments").json() if "khichdi" in t["title"].lower()]
    c.post("/api/reset")
    assert c.get("/api/skipped").json() == []
