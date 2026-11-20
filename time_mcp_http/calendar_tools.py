"""Calendar facts the model must not work out in its head: weekdays, ISO weeks,
German public holidays, working days, DST transitions and leap seconds.

Holidays come from the ``holidays`` package; without a state only the
holidays that apply in all of Germany count. Leap seconds come from the IANA
list the tzdata package of the base image installs, so no network access is
needed.
"""

import datetime
import os
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import holidays as holidays_lib
from mcp.types import Tool, ToolAnnotations

WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
STATES = tuple(sorted(s for s in holidays_lib.Germany.subdivisions if len(s) == 2))
MAX_RANGE_DAYS = 366
MAX_SHIFT_DAYS = 3660
LEAP_SECONDS_FILE = os.environ.get("LEAP_SECONDS_FILE", "/usr/share/zoneinfo/leap-seconds.list")
NTP_EPOCH = datetime.date(1900, 1, 1)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                             idempotentHint=True, openWorldHint=False)

_STATE_PROP = {
    "type": "string",
    "description": (
        "German state code for state holidays (" + ", ".join(STATES) + "). "
        "Empty means only the holidays that apply in all of Germany."
    ),
}


def _date(value: Any, name: str) -> datetime.date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required argument: {name}")
    try:
        return datetime.date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise ValueError(f"{name} must be YYYY-MM-DD, got {value!r}") from None


def _state(value: Any) -> Optional[str]:
    state = (value or "").strip().upper() if isinstance(value, str) else ""
    if not state:
        return None
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}, got {value!r}")
    return state


def _holidays(years: List[int], state: Optional[str]) -> Dict[datetime.date, str]:
    return dict(holidays_lib.Germany(subdiv=state, years=years, language="de").items())


def _day(day: datetime.date, table: Dict[datetime.date, str]) -> Dict[str, Any]:
    iso = day.isocalendar()
    out: Dict[str, Any] = {
        "date": day.isoformat(),
        "weekday": WEEKDAYS_EN[day.weekday()],
        "weekday_de": WEEKDAYS_DE[day.weekday()],
        "iso_week": f"{iso.year}-W{iso.week:02d}",
        "day_of_year": day.timetuple().tm_yday,
    }
    if day in table:
        out["holiday"] = table[day]
    out["working_day"] = day.weekday() < 5 and day not in table
    return out


def _scope(state: Optional[str]) -> str:
    return f"Germany, state {state}" if state else "Germany, nationwide holidays only"


def date_info(args: Dict[str, Any]) -> Dict[str, Any]:
    day = _date(args.get("date"), "date")
    state = _state(args.get("state"))
    out = _day(day, _holidays([day.year], state))
    out["holidays_of"] = _scope(state)
    return out


def date_range(args: Dict[str, Any]) -> Dict[str, Any]:
    start = _date(args.get("start"), "start")
    end = _date(args.get("end"), "end")
    if end < start:
        raise ValueError("end must not be before start")
    count = (end - start).days + 1
    if count > MAX_RANGE_DAYS:
        raise ValueError(f"at most {MAX_RANGE_DAYS} days per call, got {count}")
    state = _state(args.get("state"))
    table = _holidays(list(range(start.year, end.year + 1)), state)
    days = [_day(start + datetime.timedelta(days=i), table) for i in range(count)]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days_total": count,
        "working_days": sum(d["working_day"] for d in days),
        "weekend_days": sum(1 for d in days if d["weekday"] in ("Saturday", "Sunday")),
        "holidays_on_weekdays": sum(1 for d in days
                                    if "holiday" in d and d["weekday"] not in ("Saturday", "Sunday")),
        "holidays": [{"date": d["date"], "name": d["holiday"]} for d in days if "holiday" in d],
        "holidays_of": _scope(state),
        "days": days,
    }


def add_days(args: Dict[str, Any]) -> Dict[str, Any]:
    start = _date(args.get("date"), "date")
    n = args.get("days")
    if isinstance(n, bool) or not isinstance(n, int):
        raise ValueError("days must be an integer")
    if abs(n) > MAX_SHIFT_DAYS:
        raise ValueError(f"days must be between -{MAX_SHIFT_DAYS} and {MAX_SHIFT_DAYS}")
    working = bool(args.get("working_days", False))
    state = _state(args.get("state"))
    if not working:
        result = start + datetime.timedelta(days=n)
        table = _holidays([result.year], state)
    else:
        years = range(start.year - (abs(n) // 200 + 1), start.year + abs(n) // 200 + 2)
        table = _holidays(list(years), state)
        step = 1 if n >= 0 else -1
        result, left = start, abs(n)
        while left:
            result += datetime.timedelta(days=step)
            if result.weekday() < 5 and result not in table:
                left -= 1
    return {
        "from": start.isoformat(),
        "days": n,
        "counted": "working days (Monday to Friday without holidays)" if working else "calendar days",
        "holidays_of": _scope(state),
        "result": _day(result, table),
    }


def list_holidays(args: Dict[str, Any]) -> Dict[str, Any]:
    year = args.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
        raise ValueError("year must be an integer between 1900 and 2200")
    state = _state(args.get("state"))
    table = _holidays([year], state)
    return {
        "year": year,
        "holidays_of": _scope(state),
        "holidays": [_day(d, table) for d in sorted(table)],
    }


def dst_transitions(args: Dict[str, Any]) -> Dict[str, Any]:
    year = args.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
        raise ValueError("year must be an integer between 1900 and 2200")
    name = args.get("timezone") or ""
    try:
        zone = ZoneInfo(name)
    except Exception:
        raise ValueError(f"timezone must be an IANA name, got {name!r}") from None
    utc = datetime.timezone.utc
    moment = datetime.datetime(year, 1, 1, tzinfo=utc)
    stop = datetime.datetime(year + 1, 1, 1, tzinfo=utc)
    hour = datetime.timedelta(hours=1)
    found = []
    offset = moment.astimezone(zone).utcoffset()
    while moment < stop:
        nxt = moment + hour
        new = nxt.astimezone(zone).utcoffset()
        if new != offset:
            low, high = moment, nxt  # the change lies in (low, high]: narrow it to the minute
            while high - low > datetime.timedelta(minutes=1):
                mid = low + (high - low) / 2
                if mid.astimezone(zone).utcoffset() == offset:
                    low = mid
                else:
                    high = mid
            before = (high - datetime.timedelta(microseconds=1)).astimezone(zone)
            after = high.astimezone(zone)
            found.append({
                "utc": high.isoformat(),
                "local_before": before.replace(microsecond=0).isoformat(),
                "local_after": after.isoformat(),
                "offset_before": _offset(offset),
                "offset_after": _offset(new),
                "dst_after": bool(after.dst()),
            })
            offset = new
        moment = nxt
    return {"timezone": name, "year": year, "transitions": found}


def _offset(delta: Optional[datetime.timedelta]) -> str:
    minutes = int((delta or datetime.timedelta()).total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def leap_seconds(args: Dict[str, Any]) -> Dict[str, Any]:
    entries, expires, updated = [], None, None
    with open(LEAP_SECONDS_FILE, encoding="ascii") as f:
        for line in f:
            if line.startswith("#@"):
                expires = NTP_EPOCH + datetime.timedelta(seconds=int(line.split()[1]))
            elif line.startswith("#$"):
                updated = NTP_EPOCH + datetime.timedelta(seconds=int(line.split()[1]))
            elif line.strip() and not line.startswith("#"):
                seconds, tai = line.split()[:2]
                entries.append((NTP_EPOCH + datetime.timedelta(seconds=int(seconds)), int(tai)))
    leaps = []
    for (_, before), (since, after) in zip(entries, entries[1:]):
        last_day = since - datetime.timedelta(days=1)
        leaps.append({
            "utc": f"{last_day.isoformat()}T23:59:60Z" if after > before else f"{last_day.isoformat()}T23:59:59Z",
            "kind": "inserted" if after > before else "removed",
            "tai_minus_utc_after": after,
        })
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return {
        "source": "IANA leap-seconds.list of the installed tzdata",
        "list_updated": updated.isoformat() if updated else None,
        "list_expires": expires.isoformat() if expires else None,
        "list_valid_today": bool(expires and today < expires),
        "tai_minus_utc_now": entries[-1][1] if entries else None,
        "count": len(leaps),
        "last": leaps[-1] if leaps else None,
        "leap_seconds": leaps,
    }


_DATE_PROP = {"type": "string", "description": "Date as YYYY-MM-DD."}
_YEAR_PROP = {"type": "integer", "description": "Year, e.g. 2026."}

TOOLS: List[Tool] = [
    Tool(
        name="date_info",
        description=(
            "Facts about one date: weekday (English and German), ISO week, day of the year, the German "
            "public holiday on it, and whether it is a working day (Monday to Friday and no holiday)."
        ),
        inputSchema={"type": "object", "properties": {"date": _DATE_PROP, "state": _STATE_PROP},
                     "required": ["date"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="date_range",
        description=(
            f"Every day from start to end inclusive (at most {MAX_RANGE_DAYS} days) with the facts of "
            "date_info, plus the numbers of days, working days, weekend days and holidays on weekdays "
            "(working days = days - weekend days - holidays on weekdays) and the German public holidays in the period."
        ),
        inputSchema={"type": "object",
                     "properties": {"start": _DATE_PROP, "end": _DATE_PROP, "state": _STATE_PROP},
                     "required": ["start", "end"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="add_days",
        description=(
            "The date n calendar days or n working days (Monday to Friday without German public holidays) "
            "after a date; a negative n counts back. The start date itself is not counted."
        ),
        inputSchema={"type": "object", "properties": {
            "date": _DATE_PROP,
            "days": {"type": "integer", "description": "Number of days, negative to count back."},
            "working_days": {"type": "boolean", "description": "Count working days instead of calendar days."},
            "state": _STATE_PROP,
        }, "required": ["date", "days"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="list_holidays",
        description="All German public holidays of a year with date, name and weekday.",
        inputSchema={"type": "object", "properties": {"year": _YEAR_PROP, "state": _STATE_PROP},
                     "required": ["year"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="dst_transitions",
        description=(
            "The daylight saving time changes of a time zone in a year: the moment in UTC, the local "
            "clock just before and after, and the UTC offsets."
        ),
        inputSchema={"type": "object", "properties": {
            "year": _YEAR_PROP,
            "timezone": {"type": "string", "description": "IANA time zone name, e.g. Europe/Berlin."},
        }, "required": ["year", "timezone"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="leap_seconds",
        description=(
            "All leap seconds since 1972 from the IANA list, the last one, the current difference TAI "
            "minus UTC, and until when the list is valid (no leap second is announced beyond that date)."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=_READ_ONLY,
    ),
]

HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "date_info": date_info,
    "date_range": date_range,
    "add_days": add_days,
    "list_holidays": list_holidays,
    "dst_transitions": dst_transitions,
    "leap_seconds": leap_seconds,
}
