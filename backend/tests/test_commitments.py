from app.commitments import find_match, similarity, thread_key


def item(i, title, kind="task", thread=""):
    return {"id": i, "title": title, "kind": kind, "thread_id": thread}


def test_similarity_ignores_filler_words():
    assert similarity("Submit probability assignment 3", "Probability Assignment 3") == 1.0
    assert similarity("Project meeting", "Project meeting rescheduled") == 1.0


def test_numbers_must_agree():
    assert similarity("Probability assignment 3", "Probability assignment 4") == 0.0
    assert similarity("Lab 5 report", "Lab 6 report") == 0.0


def test_unrelated_titles_do_not_match():
    assert similarity("Pay semester fee", "Return library book") < 0.4


def test_thread_key_strips_reply_noise():
    assert thread_key("Re: Fwd: Project review meeting") == "project review meeting"
    assert thread_key("Correction: Assignment 3 deadline") == "assignment 3 deadline"
    assert thread_key("anything", "abc-thread") == "abc-thread"


def test_match_needs_same_kind():
    items = [item(1, "Lab 5 report", kind="task")]
    assert find_match(items, "Lab 5 report", "reply", "") is None
    assert find_match(items, "Lab 5 report", "task", "")["id"] == 1


def test_same_thread_allows_looser_titles():
    items = [item(1, "Project review meeting", kind="meeting", thread="t1")]
    assert find_match(items, "Review meeting", "meeting", "t1")["id"] == 1
    assert find_match(items, "Review meeting", "meeting", "other") is None
