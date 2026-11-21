"""Date arithmetic: periods, differences, weekdays, timestamps, durations, bridge days, meetings."""

import pytest

from time_mcp_http.app import build_server
from test_app import _call_tool


@pytest.fixture(scope="module")
def server():
    return build_server()


def _bounds(server, **args):
    out = _call_tool(server, "period_bounds", args)
    return out["start"], out["end"], out["label"]


def test_period_bounds_relative(server):
    assert _bounds(server, period="last_month", date="2026-01-15") == ("2025-12-01", "2025-12-31", "2025-12")
    assert _bounds(server, period="this_quarter", date="2026-11-05") == ("2026-10-01", "2026-12-31", "2026-Q4")
    assert _bounds(server, period="last_quarter", date="2026-02-10") == ("2025-10-01", "2025-12-31", "2025-Q4")
    assert _bounds(server, period="last_half_year", date="2026-03-01") == ("2025-07-01", "2025-12-31", "2025-H2")
    assert _bounds(server, period="next_year", date="2026-11-05") == ("2027-01-01", "2027-12-31", "2027")
    assert _bounds(server, period="last_days", days=7, date="2026-11-05")[:2] == ("2026-10-30", "2026-11-05")


def test_period_bounds_week_across_new_year(server):
    out = _call_tool(server, "period_bounds", {"period": "last_week", "date": "2027-01-01"})
    assert (out["start"], out["end"], out["label"]) == ("2026-12-21", "2026-12-27", "2026-W52")
    assert out["working_days"] == 4 and out["start_weekday_de"] == "Montag"


def test_period_bounds_explicit(server):
    out = _call_tool(server, "period_bounds", {"period": "quarter", "year": 2026, "quarter": 3})
    assert (out["start"], out["end"], out["days_total"]) == ("2026-07-01", "2026-09-30", 92)
    with pytest.raises(Exception):
        _call_tool(server, "period_bounds", {"period": "quarter", "year": 2026, "quarter": 5})
    with pytest.raises(Exception):
        _call_tool(server, "period_bounds", {"period": "fortnight"})


def test_date_diff_calendar_and_working_days(server):
    out = _call_tool(server, "date_diff", {"start": "2026-01-31", "end": "2026-02-28"})
    assert out["days"] == 28 and out["calendar"] == {"years": 0, "months": 1, "days": 0}
    out = _call_tool(server, "date_diff", {"start": "2024-02-29", "end": "2026-11-05"})
    assert out["calendar"] == {"years": 2, "months": 8, "days": 7}
    assert _call_tool(server, "date_diff", {"start": "2026-12-24", "end": "2026-12-28"})["working_days"] == 1
    back = _call_tool(server, "date_diff", {"start": "2026-12-28", "end": "2026-12-24"})
    assert back["working_days"] == -1 and back["days"] == -4


def test_date_diff_elapsed_across_dst(server):
    out = _call_tool(server, "date_diff", {"start": "2026-10-25T00:00", "end": "2026-10-25T12:00",
                                           "timezone": "Europe/Berlin"})
    assert out["elapsed"]["total_seconds"] == 13 * 3600 and out["elapsed"]["iso_duration"] == "PT13H"


def test_nth_weekday_in_month(server):
    out = _call_tool(server, "nth_weekday", {"weekday": "Freitag", "n": -1, "year": 2026, "month": 11})
    assert out["result"]["date"] == "2026-11-27" and len(out["all_in_month"]) == 4
    assert _call_tool(server, "nth_weekday", {"weekday": "Monday", "n": 1, "year": 2026, "month": 11})["result"]["date"] == "2026-11-02"
    with pytest.raises(Exception):
        _call_tool(server, "nth_weekday", {"weekday": "Friday", "n": 5, "year": 2026, "month": 11})


def test_nth_weekday_from_date(server):
    def nth(weekday, n):
        return _call_tool(server, "nth_weekday", {"weekday": weekday, "n": n, "date": "2026-11-05"})["result"]["date"]
    assert nth("Thursday", 1) == "2026-11-12" and nth("Thursday", -1) == "2026-10-29"
    assert nth("Di", 1) == "2026-11-10" and nth("Monday", 2) == "2026-11-16"


def test_convert_timestamp(server):
    out = _call_tool(server, "convert_timestamp", {"value": 0, "kind": "unix_seconds", "timezone": "Europe/Berlin"})
    assert out["utc"] == "1970-01-01T00:00:00Z" and out["local"] == "1970-01-01T01:00:00+01:00"
    assert out["excel"] == pytest.approx(25569 + 1 / 24, abs=1e-7)
    ms = _call_tool(server, "convert_timestamp", {"value": 1700000000000, "kind": "unix_milliseconds"})
    assert ms["utc"] == "2023-11-14T22:13:20Z" and ms["unix_seconds"] == 1700000000
    xl = _call_tool(server, "convert_timestamp", {"value": "45000,5", "kind": "excel", "timezone": "Europe/Berlin"})
    assert xl["local"] == "2023-03-15T12:00:00+01:00" and xl["utc"] == "2023-03-15T11:00:00Z"
    early = _call_tool(server, "convert_timestamp", {"value": 59, "kind": "excel", "timezone": "UTC"})
    assert early["local"].startswith("1900-02-28") and early["excel"] == 59
    assert _call_tool(server, "convert_timestamp", {"value": 61, "kind": "excel", "timezone": "UTC"})["local"].startswith("1900-03-01")
    iso = _call_tool(server, "convert_timestamp", {"value": "2026-11-05T16:07:00", "kind": "iso", "timezone": "Europe/Berlin"})
    assert iso["utc"] == "2026-11-05T15:07:00Z"
    for args in ({"value": 60, "kind": "excel"}, {"value": 1700000000000, "kind": "unix_seconds"}):
        with pytest.raises(Exception):
            _call_tool(server, "convert_timestamp", args)


def test_iso_duration(server):
    out = _call_tool(server, "iso_duration", {"value": "PT1H30M"})
    assert out["total_seconds"] == 5400 and out["text_de"] == "1 Stunde und 30 Minuten"
    assert _call_tool(server, "iso_duration", {"value": 5400})["iso_duration"] == "PT1H30M"
    assert _call_tool(server, "iso_duration", {"value": 90061})["iso_duration"] == "P1DT1H1M1S"
    month = _call_tool(server, "iso_duration", {"value": "P1M", "start": "2026-01-31"})
    assert month["end"] == "2026-02-28" and month["total_seconds"] is None
    # two hours of elapsed time across the spring change, one calendar day across it
    hours = _call_tool(server, "iso_duration", {"value": "PT2H", "start": "2026-03-29T01:30", "timezone": "Europe/Berlin"})
    assert hours["end"] == "2026-03-29T04:30:00+02:00"
    day = _call_tool(server, "iso_duration", {"value": "P1D", "start": "2026-03-28T12:00", "timezone": "Europe/Berlin"})
    assert day["end"] == "2026-03-29T12:00:00+02:00"
    for bad in ("P", "PT", "P1DT", "1H", "PT1H2X"):
        with pytest.raises(Exception):
            _call_tool(server, "iso_duration", {"value": bad})


def test_bridge_days(server):
    out = _call_tool(server, "bridge_days", {"year": 2026})
    assert [b["take_off"][0]["date"] for b in out["bridges"]] == ["2026-01-02", "2026-05-15"]
    may = out["bridges"][1]
    assert (may["free_from"], may["free_until"], may["free_days"]) == ("2026-05-14", "2026-05-17", 4)
    nw = _call_tool(server, "bridge_days", {"year": 2026, "state": "NW"})
    assert "2026-06-05" in [b["take_off"][0]["date"] for b in nw["bridges"]]


def test_meeting_times(server):
    out = _call_tool(server, "meeting_times", {"timezones": ["America/New_York", "Asia/Kolkata"],
                                               "timezone": "Europe/Berlin", "date": "2026-11-05", "time": "15:00"})
    zones = {z["timezone"]: z for z in out["zones"]}
    assert zones["America/New_York"]["local"] == "2026-11-05T09:00:00-05:00"
    assert zones["America/New_York"]["in_working_hours"] is True
    assert zones["Asia/Kolkata"]["in_working_hours"] is False and out["overlap"] is None
    two = _call_tool(server, "meeting_times", {"timezones": ["America/New_York"], "timezone": "Europe/Berlin",
                                               "date": "2026-11-05"})
    assert two["overlap"]["minutes"] == 120 and two["overlap"]["local"]["Europe/Berlin"] == "15:00-17:00"
    assert two["overlap"]["local"]["America/New_York"] == "09:00-11:00"
    with pytest.raises(Exception):
        _call_tool(server, "meeting_times", {"timezones": ["Mars/Base"]})
