from app.textnorm import (clean_subject, content_tokens, date_tokens, split_sentences,
                          subject_key, text_date_tokens)


def test_clean_subject():
    cases = {
        "Re: Project review meeting - rescheduled": "Project review meeting",
        "Correction: Probability Assignment 3 deadline": "Probability Assignment 3",
        "Lab 5 report due Thursday": "Lab 5 report",
        "Summer internship applications open": "Summer internship applications",
        "Book return reminder": "Book return",
        "Mid-semester examination timetable": "Mid-semester examination timetable",
        "Re: Fwd: Project review meeting": "Project review meeting",
    }
    for raw, want in cases.items():
        assert clean_subject(raw) == want, raw


def test_subject_key_matches_original_and_correction():
    assert subject_key("Probability Assignment 3") == subject_key("Correction: Probability Assignment 3 deadline")
    assert subject_key("Project review meeting") == subject_key("Re: Project review meeting - rescheduled")
    assert subject_key("Lab 5 report due Thursday") != subject_key("Lab 5 viva slots")


def test_date_tokens_are_canonical():
    assert date_tokens("November 9th, 10:00 AM") <= text_date_tokens("Data Structures exam: 9 November, 10:00 AM, Room LH-2.")
    assert date_tokens("Thu by 5pm") <= text_date_tokens("due this Thursday by 5 PM")
    assert date_tokens("Oct 23") <= text_date_tokens("Friday 23 October")
    assert not date_tokens("Tuesday 20 October 2026") <= text_date_tokens("Please submit by Thursday 22 October")
    assert date_tokens("at 10 AM") <= text_date_tokens("Meeting at 10:00 AM")


def test_content_tokens_ignore_filler_and_plurals():
    assert content_tokens("Submit the slides") == content_tokens("slide")
    assert "form" not in content_tokens("Fill the form")
    assert "form" in content_tokens("Fill the form", drop_weak=False)


def test_sentences_are_exact_substrings_and_respect_abbreviations():
    text = "Please return it by 25 October to avoid a fine of Rs. 5 per day.\n\nHello Dr. Rao, see you.\n* one\n* two"
    sents = split_sentences(text)
    assert [s for _, _, s in sents] == [
        "Please return it by 25 October to avoid a fine of Rs. 5 per day.",
        "Hello Dr. Rao, see you.", "* one", "* two"]
    for a, b, s in sents:
        assert text[a:b] == s


def test_hard_wrapped_lines_stay_one_sentence():
    text = "The assignment is due\nFriday 23 October at 5 PM. Thanks."
    assert [s for _, _, s in split_sentences(text)][0] == "The assignment is due\nFriday 23 October at 5 PM."
