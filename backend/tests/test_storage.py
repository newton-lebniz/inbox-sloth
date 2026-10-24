import sqlite3

from app.db import Store

DAY1_SCHEMA = """
CREATE TABLE emails (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL DEFAULT '', sender TEXT NOT NULL,
  subject TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
  category TEXT, summary TEXT, error TEXT, processed_at TEXT);
CREATE TABLE commitments (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'task',
  due_at TEXT, all_day INTEGER NOT NULL DEFAULT 0, date_phrase TEXT NOT NULL DEFAULT '',
  date_confidence TEXT NOT NULL DEFAULT 'none', details TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending', thread_id TEXT NOT NULL DEFAULT '', flags TEXT NOT NULL DEFAULT '[]',
  previous_due_at TEXT, source_email_id TEXT NOT NULL, first_email_id TEXT NOT NULL,
  source_quote TEXT NOT NULL DEFAULT '', last_sent_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE commitment_events (id INTEGER PRIMARY KEY AUTOINCREMENT, commitment_id INTEGER NOT NULL,
  email_id TEXT NOT NULL, event TEXT NOT NULL, old_due_at TEXT, new_due_at TEXT, at TEXT NOT NULL);
CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
"""


def test_day1_database_is_migrated_in_place(tmp_path):
    path = str(tmp_path / "day1.db")
    con = sqlite3.connect(path)
    con.executescript(DAY1_SCHEMA)
    con.execute("INSERT INTO commitments (title, source_email_id, first_email_id, last_sent_at, created_at, updated_at)"
                " VALUES ('Old task', 'e1', 'e1', 'x', 'x', 'x')")
    con.commit()
    con.close()

    store = Store(path)                                    # must not raise
    (old,) = store.list_commitments()
    assert old["title"] == "Old task" and old["origin"] == "model"
    cid = store.insert_commitment({"title": "New", "kind": "task", "email_id": "e2", "sent_at": "x", "origin": "rules"})
    assert store.get_commitment(cid)["origin"] == "rules"
    store.add_skipped("e2", "t", "informational")
    store.cache_put("k", "m", {"a": 1})
    assert store.cache_get("k") == {"a": 1} and len(store.list_skipped()) == 1
    Store(path)                                            # opening twice is fine


def test_reset_results_keeps_emails_and_cache(store):
    store.add_emails([{"id": "e1", "thread_id": "", "sender": "s", "subject": "S", "body": "b", "sent_at": "2026-10-19T09:00:00"}])
    store.save_email_result("e1", "processed", "other", "x")
    store.insert_commitment({"title": "T", "kind": "task", "email_id": "e1", "sent_at": "2026-10-19T09:00:00"})
    store.cache_put("k", "m", {"a": 1})
    store.reset_results()
    assert store.list_commitments() == [] and store.get_email("e1")["status"] == "new"
    assert store.cache_size() == 1
    store.reset()
    assert store.list_emails() == [] and store.cache_size() == 1     # the model cache survives a reset
