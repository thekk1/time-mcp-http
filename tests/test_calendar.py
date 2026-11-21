"""Calendar tools: weekdays, holidays, working days, DST and leap seconds."""

import pytest

from time_mcp_http.app import build_server
from test_app import _call_tool


@pytest.fixture(scope="module")
def server():
    return build_server()


def test_date_info_weekday_week_and_working_day(server):
    out = _call_tool(server, "date_info", {"date": "2026-11-05"})
    assert out["weekday"] == "Thursday" and out["weekday_de"] == "Donnerstag"
    assert out["iso_week"] == "2026-W45" and out["day_of_year"] == 309
    assert out["working_day"] is True and "holiday" not in out


def test_iso_week_belongs_to_the_next_year(server):
    assert _call_tool(server, "date_info", {"date": "2024-12-30"})["iso_week"] == "2025-W01"


def test_nationwide_holiday_without_state(server):
    out = _call_tool(server, "date_info", {"date": "2026-10-03"})
    assert out["holiday"] == "Tag der Deutschen Einheit" and out["working_day"] is False
    assert out["holidays_of"] == "Germany, nationwide holidays only"


def test_state_holiday_only_with_state(server):
    assert "holiday" not in _call_tool(server, "date_info", {"date": "2026-11-01"})
    # Allerheiligen falls on a Sunday in 2026: a holiday, and no working day anyway
    nw = _call_tool(server, "date_info", {"date": "2026-11-01", "state": "nw"})
    assert nw["holiday"] == "Allerheiligen" and nw["holidays_of"] == "Germany, state NW"
    assert "holiday" in _call_tool(server, "date_info", {"date": "2026-06-04", "state": "BW"})
    assert "holiday" not in _call_tool(server, "date_info", {"date": "2026-06-04", "state": "BE"})


def test_unknown_state_is_rejected(server):
    with pytest.raises(Exception):
        _call_tool(server, "date_info", {"date": "2026-11-05", "state": "XX"})


def test_bad_date_is_rejected(server):
    with pytest.raises(Exception):
        _call_tool(server, "date_info", {"date": "05.11.2026"})


def test_date_range_counts_working_days_and_holidays(server):
    out = _call_tool(server, "date_range", {"start": "2026-12-21", "end": "2027-01-03"})
    assert out["days_total"] == 14 and len(out["days"]) == 14
    # Mon 21. to Fri 2. January: ten weekdays minus 25.12. (Fri) and 1.1. (Fri); 26.12. is a Saturday
    assert out["working_days"] == 8 and out["weekend_days"] == 4 and out["holidays_on_weekdays"] == 2
    dec = _call_tool(server, "date_range", {"start": "2026-12-01", "end": "2026-12-31", "state": "NW"})
    assert (dec["working_days"], dec["weekend_days"], dec["holidays_on_weekdays"]) == (22, 8, 1)
    assert [h["date"] for h in out["holidays"]] == ["2026-12-25", "2026-12-26", "2027-01-01"]


def test_date_range_limits(server):
    with pytest.raises(Exception):
        _call_tool(server, "date_range", {"start": "2026-01-02", "end": "2026-01-01"})
    with pytest.raises(Exception):
        _call_tool(server, "date_range", {"start": "2026-01-01", "end": "2027-01-02"})


def test_add_working_days_skips_weekend_and_holidays(server):
    # Thu 24.12.2026 + 1 working day: Fri 25. and Mon 28.? 25.12. is a holiday, 26./27. weekend
    out = _call_tool(server, "add_days", {"date": "2026-12-24", "days": 1, "working_days": True})
    assert out["result"]["date"] == "2026-12-28"
    back = _call_tool(server, "add_days", {"date": "2026-12-28", "days": -1, "working_days": True})
    assert back["result"]["date"] == "2026-12-24"
    cal = _call_tool(server, "add_days", {"date": "2026-11-05", "days": 30})
    assert cal["result"]["date"] == "2026-12-05" and cal["result"]["weekday"] == "Saturday"


def test_list_holidays_nationwide_and_state(server):
    de = _call_tool(server, "list_holidays", {"year": 2026})
    assert len(de["holidays"]) == 9
    nw = _call_tool(server, "list_holidays", {"year": 2026, "state": "NW"})
    assert len(nw["holidays"]) == 11
    assert de["holidays"][1]["date"] == "2026-04-03" and de["holidays"][1]["weekday_de"] == "Freitag"


def test_dst_transitions_berlin(server):
    out = _call_tool(server, "dst_transitions", {"year": 2026, "timezone": "Europe/Berlin"})
    spring, autumn = out["transitions"]
    assert spring["utc"] == "2026-03-29T01:00:00+00:00"
    assert spring["local_before"] == "2026-03-29T01:59:59+01:00"
    assert spring["local_after"] == "2026-03-29T03:00:00+02:00" and spring["dst_after"] is True
    assert autumn["utc"] == "2026-10-25T01:00:00+00:00"
    assert autumn["local_after"] == "2026-10-25T02:00:00+01:00" and autumn["dst_after"] is False


def test_dst_transitions_zone_without_dst(server):
    assert _call_tool(server, "dst_transitions", {"year": 2026, "timezone": "Asia/Riyadh"})["transitions"] == []


def test_leap_seconds(server):
    out = _call_tool(server, "leap_seconds", {})
    assert out["count"] == 27 and out["tai_minus_utc_now"] == 37
    assert out["last"] == {"utc": "2016-12-31T23:59:60Z", "kind": "inserted", "tai_minus_utc_after": 37}
    assert out["leap_seconds"][0]["utc"] == "1972-06-30T23:59:60Z"
    assert out["list_expires"] > "2026-01-01"


def test_calendar_week_from_year_and_week(server):
    out = _call_tool(server, "calendar_week", {"year": 2026, "week": 45})
    assert (out["start"], out["end"], out["iso_week"]) == ("2026-11-02", "2026-11-08", "2026-W45")
    assert out["working_days"] == 5 and out["weeks_in_year"] == 53


def test_calendar_week_from_date_across_new_year(server):
    out = _call_tool(server, "calendar_week", {"date": "2027-01-01"})
    # 1 January 2027 is a Friday in week 53 of ISO year 2026; Neujahr is a holiday
    assert (out["year"], out["week"], out["start"], out["end"]) == (2026, 53, "2026-12-28", "2027-01-03")
    assert out["working_days"] == 4 and out["holidays"] == [{"date": "2027-01-01", "name": "Neujahr"}]
    assert _call_tool(server, "calendar_week", {"date": "2024-12-30"})["iso_week"] == "2025-W01"


def test_calendar_week_rejects_bad_input(server):
    for args in ({"year": 2025, "week": 53}, {"year": 2026, "week": 0}, {}, {"date": "2026-11-05", "week": 45}):
        with pytest.raises(Exception):
            _call_tool(server, "calendar_week", args)
