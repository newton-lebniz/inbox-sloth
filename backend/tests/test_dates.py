from datetime import datetime

from app.dates import resolve

MON = datetime(2026, 10, 19, 9, 10)   # Monday
WED = datetime(2026, 10, 21, 8, 30)   # Wednesday


def ok(phrase, sent, expected, all_day=False, conf=None):
    r = resolve(phrase, sent)
    assert r.due == expected, (phrase, r)
    assert r.all_day == all_day, (phrase, r)
    if conf:
        assert r.confidence == conf, (phrase, r)


def test_explicit_date_and_time():
    ok("Friday 23 October, 11:59 PM", MON, datetime(2026, 10, 23, 23, 59), conf="high")
    ok("Saturday, 24 October at 10:00 AM", MON, datetime(2026, 10, 24, 10, 0), conf="high")
    ok("9 November, 10:00 AM", WED, datetime(2026, 11, 9, 10, 0))
    ok("October 30, 2026", WED, datetime(2026, 10, 30, 23, 59), all_day=True)
    ok("2026-11-02", MON, datetime(2026, 11, 2, 23, 59), all_day=True)


def test_weekday_relative_to_sent_date():
    ok("Thursday 5 PM", MON, datetime(2026, 10, 22, 17, 0), conf="high")
    ok("this Wednesday at 4 PM", MON, datetime(2026, 10, 21, 16, 0))
    ok("Monday 9:00 AM", WED, datetime(2026, 10, 26, 9, 0))
    ok("by Friday", MON, datetime(2026, 10, 23, 23, 59), all_day=True)


def test_next_weekday_is_next_calendar_week():
    r = resolve("next Thursday", MON)
    assert r.due.date() == datetime(2026, 10, 29).date()
    assert r.confidence == "medium"


def test_same_weekday_is_flagged():
    r = resolve("Wednesday", WED)
    assert r.due.date() == WED.date()
    assert r.confidence == "medium"


def test_tomorrow_today_and_in_n_days():
    ok("tomorrow 6 PM", datetime(2026, 10, 20, 21, 10), datetime(2026, 10, 21, 18, 0))
    ok("today by 4pm", MON, datetime(2026, 10, 19, 16, 0))
    ok("day after tomorrow", MON, datetime(2026, 10, 21, 23, 59), all_day=True)
    ok("in 2 weeks", MON, datetime(2026, 11, 2, 23, 59), all_day=True, conf="medium")


def test_time_formats():
    ok("Thursday 11 AM", MON, datetime(2026, 10, 22, 11, 0))
    ok("Thursday 11:30am", MON, datetime(2026, 10, 22, 11, 30))
    ok("Thursday 16:45", MON, datetime(2026, 10, 22, 16, 45))
    ok("Thursday noon", MON, datetime(2026, 10, 22, 12, 0))
    ok("Thursday 12 AM", MON, datetime(2026, 10, 22, 0, 0))
    r = resolve("Friday EOD", MON)
    assert r.due == datetime(2026, 10, 23, 17, 0) and r.confidence == "medium"


def test_time_digits_are_not_read_as_day_numbers():
    # "4 PM" must not become the 4th of the month
    ok("Wednesday 4 PM", MON, datetime(2026, 10, 21, 16, 0))


def test_numeric_dates_are_day_first():
    r = resolve("23/10", MON)
    assert r.due.date() == datetime(2026, 10, 23).date()
    r = resolve("5/11/2026", MON)
    assert r.due.date() == datetime(2026, 11, 5).date()


def test_year_rollover_and_past_dates():
    dec = datetime(2026, 12, 28, 10, 0)
    assert resolve("5 January", dec).due.date() == datetime(2027, 1, 5).date()
    r = resolve("3 October 2026", MON)
    assert r.confidence == "low"  # before the email was sent


def test_nothing_to_parse():
    for phrase in ["", "soon", "as soon as possible", "sometime next month"]:
        r = resolve(phrase, MON)
        assert r.due is None and r.confidence == "none", phrase


def test_time_only_is_low_confidence():
    r = resolve("by 4 PM", MON)
    assert r.due == datetime(2026, 10, 19, 16, 0) and r.confidence == "low"
