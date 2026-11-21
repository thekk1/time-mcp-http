"""Date and time arithmetic a model gets wrong in its head: the bounds of
relative periods, the distance between two dates, the n-th weekday of a month,
timestamps and ISO durations, bridge days and meeting times across time zones.

Holidays and working days come from calendar_tools, so they follow the same
rule: without a state only the holidays that apply in all of Germany count.
"""

import datetime
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.types import Tool

from time_mcp_http.calendar_tools import (
    MAX_SHIFT_DAYS, WEEKDAYS_DE, WEEKDAYS_EN, _READ_ONLY, _STATE_PROP,
    _date, _day, _holidays, _scope, _state,
)

UTC = datetime.timezone.utc
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=UTC)
EXCEL_EPOCH = datetime.datetime(1899, 12, 30)  # serial 0 with Excel's 29 February 1900 accounted for
MAX_ZONES = 12
MAX_BRIDGE_DAYS = 3

PERIODS = (
    "today", "yesterday", "tomorrow",
    "this_week", "last_week", "next_week",
    "this_month", "last_month", "next_month",
    "this_quarter", "last_quarter", "next_quarter",
    "this_half_year", "last_half_year", "next_half_year",
    "this_year", "last_year", "next_year",
    "last_days", "next_days",
    "month", "quarter", "half_year", "year",
)


def _local_zone() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("LOCAL_TIMEZONE") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _zone(value: Any) -> ZoneInfo:
    if value is None or (isinstance(value, str) and not value.strip()):
        return _local_zone()
    if not isinstance(value, str):
        raise ValueError(f"timezone must be an IANA name such as Europe/Berlin, got {value!r}")
    try:
        return ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown timezone {value!r}, use an IANA name such as Europe/Berlin") from None


def _int(args: Dict[str, Any], name: str, low: int, high: int, default: Optional[int] = None) -> int:
    value = args.get(name, default)
    if value is None:
        raise ValueError(f"Missing required argument: {name}")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value


def _today(args: Dict[str, Any]) -> datetime.date:
    if args.get("date"):
        return _date(args.get("date"), "date")
    return datetime.datetime.now(_local_zone()).date()


def _add_months(day: datetime.date, months: int) -> datetime.date:
    """Shift by whole months; a day that the target month lacks becomes its last day."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    last = (datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day.day, last))


def _month_bounds(year: int, month: int) -> Tuple[datetime.date, datetime.date]:
    start = datetime.date(year, month, 1)
    return start, _add_months(start, 1) - datetime.timedelta(days=1)


def _span(start: datetime.date, end: datetime.date, state: Optional[str]) -> Dict[str, Any]:
    table = _holidays(list(range(start.year, end.year + 1)), state)
    count = (end - start).days + 1
    days = [start + datetime.timedelta(days=i) for i in range(count)]
    return {
        "start": start.isoformat(),
        "start_weekday_de": WEEKDAYS_DE[start.weekday()],
        "end": end.isoformat(),
        "end_weekday_de": WEEKDAYS_DE[end.weekday()],
        "days_total": count,
        "working_days": sum(1 for d in days if d.weekday() < 5 and d not in table),
        "holidays": [{"date": d.isoformat(), "name": table[d]} for d in days if d in table],
        "holidays_of": _scope(state),
    }


# --- period_bounds -----------------------------------------------------------

def period_bounds(args: Dict[str, Any]) -> Dict[str, Any]:
    period = args.get("period")
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}, got {period!r}")
    ref = _today(args)
    state = _state(args.get("state"))
    label = ""
    if period in ("today", "yesterday", "tomorrow"):
        start = end = ref + datetime.timedelta(days={"today": 0, "yesterday": -1, "tomorrow": 1}[period])
        label = start.isoformat()
    elif period.endswith("_week"):
        shift = {"this": 0, "last": -1, "next": 1}[period.split("_")[0]]
        start = ref - datetime.timedelta(days=ref.weekday()) + datetime.timedelta(weeks=shift)
        end = start + datetime.timedelta(days=6)
        iso = start.isocalendar()
        label = f"{iso.year}-W{iso.week:02d}"
    elif period in ("last_days", "next_days"):
        n = _int(args, "days", 1, MAX_SHIFT_DAYS)
        if period == "last_days":
            start, end = ref - datetime.timedelta(days=n - 1), ref
        else:
            start, end = ref, ref + datetime.timedelta(days=n - 1)
        label = f"{n} days {'ending' if period == 'last_days' else 'starting'} {ref.isoformat()}"
    else:
        unit = period.split("_", 1)[1] if "_" in period and period.split("_")[0] in ("this", "last", "next") else period
        shift = {"this": 0, "last": -1, "next": 1}.get(period.split("_")[0], 0)
        explicit = period in ("month", "quarter", "half_year", "year")
        year = _int(args, "year", 1900, 2200) if explicit else ref.year
        if unit == "month":
            month = _int(args, "month", 1, 12) if explicit else ref.month
            first = _add_months(datetime.date(year, month, 1), shift)
            start, end = _month_bounds(first.year, first.month)
            label = f"{start.year}-{start.month:02d}"
        elif unit in ("quarter", "half_year"):
            size = 3 if unit == "quarter" else 6
            if explicit:
                number = _int(args, unit, 1, 12 // size)
            else:
                number = (ref.month - 1) // size + 1
            first = _add_months(datetime.date(year, (number - 1) * size + 1, 1), shift * size)
            start = first
            end = _add_months(first, size) - datetime.timedelta(days=1)
            number = (first.month - 1) // size + 1
            label = f"{first.year}-{'Q' if size == 3 else 'H'}{number}"
        else:
            start = datetime.date(year + shift, 1, 1)
            end = datetime.date(year + shift, 12, 31)
            label = str(start.year)
    out = {"period": period, "reference_date": ref.isoformat(), "label": label}
    out.update(_span(start, end, state))
    return out


# --- date_diff ---------------------------------------------------------------

def _moment(value: Any, name: str, zone: ZoneInfo) -> Tuple[datetime.datetime, bool]:
    """A date or a date with time; a time without offset is local time in zone."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required argument: {name}")
    text = value.strip().replace(" ", "T", 1)
    if "T" not in text:
        return datetime.datetime.combine(_date(text, name), datetime.time(), zone), False
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS][+HH:MM], got {value!r}") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment, True


def _calendar_parts(start: datetime.date, end: datetime.date) -> Dict[str, int]:
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    months = (end.year - start.year) * 12 + end.month - start.month
    if _add_months(start, months) > end:
        months -= 1
    days = (end - _add_months(start, months)).days
    return {"years": sign * (months // 12), "months": sign * (months % 12), "days": sign * days}


def _working_days_between(start: datetime.date, end: datetime.date, state: Optional[str]) -> int:
    """Working days after start up to and including end; negative when end lies before start."""
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    if (end - start).days > MAX_SHIFT_DAYS:
        raise ValueError(f"working days are counted for at most {MAX_SHIFT_DAYS} days")
    table = _holidays(list(range(start.year, end.year + 1)), state)
    count = 0
    day = start
    while day < end:
        day += datetime.timedelta(days=1)
        if day.weekday() < 5 and day not in table:
            count += 1
    return sign * count


def date_diff(args: Dict[str, Any]) -> Dict[str, Any]:
    zone = _zone(args.get("timezone"))
    state = _state(args.get("state"))
    start, start_timed = _moment(args.get("start"), "start", zone)
    end, end_timed = _moment(args.get("end"), "end", zone)
    days = (end.date() - start.date()).days
    out: Dict[str, Any] = {
        "start": start.isoformat() if start_timed else start.date().isoformat(),
        "end": end.isoformat() if end_timed else end.date().isoformat(),
        "days": days,
        "weeks": {"weeks": int(days / 7), "days": days - int(days / 7) * 7},
        "calendar": _calendar_parts(start.date(), end.date()),
        "working_days": _working_days_between(start.date(), end.date(), state),
        "holidays_of": _scope(state),
    }
    if start_timed or end_timed:
        seconds = int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds())
        rest = abs(seconds)
        out["elapsed"] = {
            "total_seconds": seconds,
            "total_hours": round(seconds / 3600, 4),
            "sign": "-" if seconds < 0 else "+",
            "days": rest // 86400, "hours": rest % 86400 // 3600,
            "minutes": rest % 3600 // 60, "seconds": rest % 60,
            "iso_duration": _format_duration(seconds),
        }
        out["timezone"] = str(zone)
    return out


# --- nth_weekday -------------------------------------------------------------

_WEEKDAY_NAMES = {name.lower(): i for i, name in enumerate(WEEKDAYS_EN)}
_WEEKDAY_NAMES.update({name.lower(): i for i, name in enumerate(WEEKDAYS_DE)})
_WEEKDAY_NAMES.update({name[:3].lower(): i for i, name in enumerate(WEEKDAYS_EN)})
_WEEKDAY_NAMES.update({name[:2].lower(): i for i, name in enumerate(WEEKDAYS_DE)})


def _weekday(value: Any) -> int:
    key = value.strip().lower() if isinstance(value, str) else None
    if key not in _WEEKDAY_NAMES:
        raise ValueError(f"weekday must be a weekday name such as Monday or Montag, got {value!r}")
    return _WEEKDAY_NAMES[key]


def nth_weekday(args: Dict[str, Any]) -> Dict[str, Any]:
    weekday = _weekday(args.get("weekday"))
    n = args.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n == 0:
        raise ValueError("n must be a non-zero integer")
    state = _state(args.get("state"))
    out: Dict[str, Any] = {"weekday": WEEKDAYS_EN[weekday], "weekday_de": WEEKDAYS_DE[weekday], "n": n}
    if args.get("date"):
        if args.get("year") is not None or args.get("month") is not None:
            raise ValueError("pass either date, or year and month")
        if abs(n) > 520:
            raise ValueError("n must be between -520 and 520 with a date")
        ref = _date(args.get("date"), "date")
        step = 1 if n > 0 else -1
        ahead = (weekday - ref.weekday()) % 7 if n > 0 else (ref.weekday() - weekday) % 7
        first = ref + datetime.timedelta(days=step * (ahead or 7))  # the date itself never counts
        result = first + datetime.timedelta(weeks=step * (abs(n) - 1))
        out["from"] = ref.isoformat()
        out["counted"] = ("after" if n > 0 else "before") + " the date, the date itself not counted"
    else:
        year = _int(args, "year", 1900, 2200)
        month = _int(args, "month", 1, 12)
        start, end = _month_bounds(year, month)
        first = start + datetime.timedelta(days=(weekday - start.weekday()) % 7)
        all_days = [first + datetime.timedelta(weeks=i) for i in range(6) if first + datetime.timedelta(weeks=i) <= end]
        if abs(n) > len(all_days):
            raise ValueError(f"{year}-{month:02d} has {len(all_days)} {WEEKDAYS_EN[weekday]}s, got n={n}")
        result = all_days[n - 1] if n > 0 else all_days[n]
        out["month"] = f"{year}-{month:02d}"
        out["counted"] = "from the start of the month" if n > 0 else "from the end of the month (-1 is the last)"
        out["all_in_month"] = [d.isoformat() for d in all_days]
    table = _holidays([result.year], state)
    out["result"] = _day(result, table)
    out["holidays_of"] = _scope(state)
    return out


# --- convert_timestamp -------------------------------------------------------

TIMESTAMP_KINDS = ("unix_seconds", "unix_milliseconds", "excel", "iso")


def _excel_serial(value: float) -> datetime.datetime:
    if value < 1:
        raise ValueError("Excel serials start at 1 (1900-01-01)")
    if 60 <= value < 61:
        raise ValueError("Excel serial 60 is 29 February 1900, a day that does not exist")
    # Excel counts the non-existent 29 February 1900, so serials below 60 are one day off
    base = EXCEL_EPOCH + datetime.timedelta(days=1) if value < 60 else EXCEL_EPOCH
    return base + datetime.timedelta(days=value)


def _to_excel(local: datetime.datetime) -> float:
    naive = local.replace(tzinfo=None)
    serial = (naive - EXCEL_EPOCH).total_seconds() / 86400
    if serial < 61:
        serial -= 1
    return round(serial, 8)


def convert_timestamp(args: Dict[str, Any]) -> Dict[str, Any]:
    kind = args.get("kind")
    if kind not in TIMESTAMP_KINDS:
        raise ValueError(f"kind must be one of {', '.join(TIMESTAMP_KINDS)}, got {kind!r}")
    zone = _zone(args.get("timezone"))
    value = args.get("value")
    if kind == "iso":
        moment, timed = _moment(value if isinstance(value, str) else None, "value", zone)
    else:
        if isinstance(value, str):
            try:
                value = float(value.strip().replace(",", "."))
            except ValueError:
                raise ValueError(f"value must be a number for kind {kind}, got {args.get('value')!r}") from None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"value must be a number for kind {kind}")
        if kind == "unix_seconds" and abs(value) > 1e11:
            raise ValueError(f"{value} as Unix seconds lies after the year 5000; a 13-digit value is "
                             "milliseconds, use kind unix_milliseconds")
        try:
            if kind == "unix_seconds":
                moment = EPOCH + datetime.timedelta(seconds=value)
            elif kind == "unix_milliseconds":
                moment = EPOCH + datetime.timedelta(milliseconds=value)
            else:
                moment = _excel_serial(float(value)).replace(tzinfo=zone)
        except OverflowError:
            raise ValueError(f"value {value} lies outside the supported years") from None
    if not 1900 <= moment.year <= 2200:
        raise ValueError(f"the timestamp lies in {moment.year}, outside 1900 to 2200")
    local = moment.astimezone(zone)
    seconds = (moment.astimezone(UTC) - EPOCH).total_seconds()
    out = {
        "kind": kind,
        "value": args.get("value"),
        "utc": moment.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "local": local.isoformat(),
        "timezone": str(zone),
        "weekday_de": WEEKDAYS_DE[local.weekday()],
        "unix_seconds": int(seconds) if seconds == int(seconds) else round(seconds, 6),
        "unix_milliseconds": round(seconds * 1000),
        "excel": _to_excel(local),
    }
    if kind == "excel":
        out["note"] = "Excel serials have no time zone; read as local time in timezone"
    return out


# --- iso_duration ------------------------------------------------------------

_DURATION = re.compile(
    r"^(?P<sign>[-+])?P(?:(?P<years>\d+(?:[.,]\d+)?)Y)?(?:(?P<months>\d+(?:[.,]\d+)?)M)?"
    r"(?:(?P<weeks>\d+(?:[.,]\d+)?)W)?(?:(?P<days>\d+(?:[.,]\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:[.,]\d+)?)H)?(?:(?P<minutes>\d+(?:[.,]\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:[.,]\d+)?)S)?)?$"
)
_DURATION_UNITS = ("years", "months", "weeks", "days", "hours", "minutes", "seconds")
_UNIT_SECONDS = {"weeks": 604800, "days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}
_UNIT_DE = {"years": ("Jahr", "Jahre"), "months": ("Monat", "Monate"), "weeks": ("Woche", "Wochen"),
            "days": ("Tag", "Tage"), "hours": ("Stunde", "Stunden"), "minutes": ("Minute", "Minuten"),
            "seconds": ("Sekunde", "Sekunden")}


def _format_duration(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    rest = abs(seconds)
    days, rest = divmod(rest, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    out = f"{sign}P" + (f"{int(days)}D" if days else "")
    time = (f"{int(hours)}H" if hours else "") + (f"{int(minutes)}M" if minutes else "")
    if secs:
        time += (f"{secs:g}" if secs != int(secs) else str(int(secs))) + "S"
    if time:
        out += "T" + time
    return out if out not in ("P", "-P") else "PT0S"


def _german(parts: Dict[str, float]) -> str:
    words = []
    for unit in _DURATION_UNITS:
        value = parts.get(unit)
        if value:
            shown = f"{value:g}".replace(".", ",")
            words.append(f"{shown} {_UNIT_DE[unit][0] if value == 1 else _UNIT_DE[unit][1]}")
    return ", ".join(words[:-1]) + (" und " if len(words) > 1 else "") + words[-1] if words else "0 Sekunden"


def iso_duration(args: Dict[str, Any]) -> Dict[str, Any]:
    value = args.get("value")
    zone = _zone(args.get("timezone"))
    if isinstance(value, bool):
        raise ValueError("value must be an ISO 8601 duration such as PT1H30M or a number of seconds")
    if isinstance(value, (int, float)):
        seconds = float(value)
        out: Dict[str, Any] = {"value": value, "iso_duration": _format_duration(seconds),
                               "total_seconds": int(seconds) if seconds == int(seconds) else seconds}
        rest = abs(seconds)
        parts = {"days": rest // 86400, "hours": rest % 86400 // 3600, "minutes": rest % 3600 // 60,
                 "seconds": rest % 60}
        parts = {k: int(v) if v == int(v) else v for k, v in parts.items()}
        out["parts"] = parts
        out["text_de"] = ("minus " if seconds < 0 else "") + _german(parts)
        return out
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing required argument: value")
    match = _DURATION.match(value.strip().upper())
    if not match or value.strip().upper().rstrip("T").endswith(("P", "-P")) or value.strip().upper().endswith("T"):
        raise ValueError(f"value must be an ISO 8601 duration such as P1DT2H or PT90M, got {value!r}")
    parts = {u: float(match.group(u).replace(",", ".")) for u in _DURATION_UNITS if match.group(u)}
    parts = {k: int(v) if v == int(v) else v for k, v in parts.items()}
    sign = -1 if match.group("sign") == "-" else 1
    out = {"value": value, "parts": parts, "negative": sign < 0,
           "text_de": ("minus " if sign < 0 else "") + _german(parts)}
    if not (parts.get("years") or parts.get("months")):
        total = sign * sum(v * _UNIT_SECONDS[k] for k, v in parts.items())
        out["total_seconds"] = int(total) if total == int(total) else total
        out["total_hours"] = round(total / 3600, 4)
    else:
        out["total_seconds"] = None
        out["note"] = "years and months have no fixed length; pass start to get the end"
    if args.get("start"):
        if any(isinstance(parts.get(u), float) for u in ("years", "months")):
            raise ValueError("fractional years or months cannot be added to a date")
        start, timed = _moment(args.get("start"), "start", zone)
        months = sign * (parts.get("years", 0) * 12 + parts.get("months", 0))
        shifted_day = _add_months(start.date(), int(months))
        shifted = datetime.datetime.combine(shifted_day, start.timetz())
        # days count in calendar days (wall clock), hours and smaller in elapsed time
        shifted += datetime.timedelta(days=sign * (parts.get("weeks", 0) * 7 + parts.get("days", 0)))
        shifted = shifted.replace(tzinfo=start.tzinfo)
        elapsed = sign * sum(parts.get(u, 0) * _UNIT_SECONDS[u] for u in ("hours", "minutes", "seconds"))
        end = (shifted.astimezone(UTC) + datetime.timedelta(seconds=elapsed)).astimezone(start.tzinfo)
        has_time = timed or bool(elapsed) or isinstance(parts.get("days"), float) or isinstance(parts.get("weeks"), float)
        out["start"] = start.isoformat() if timed else start.date().isoformat()
        out["end"] = end.isoformat() if has_time else end.date().isoformat()
        out["end_weekday_de"] = WEEKDAYS_DE[end.weekday()]
    return out


# --- bridge_days -------------------------------------------------------------

def bridge_days(args: Dict[str, Any]) -> Dict[str, Any]:
    year = _int(args, "year", 1900, 2200)
    max_days = _int(args, "max_days", 1, MAX_BRIDGE_DAYS, default=1)
    state = _state(args.get("state"))
    table = _holidays([year - 1, year, year + 1], state)

    def free(day: datetime.date) -> bool:
        return day.weekday() >= 5 or day in table

    found: List[Dict[str, Any]] = []
    day = datetime.date(year, 1, 1)
    last = datetime.date(year, 12, 31)
    while day <= last:
        if free(day):
            day += datetime.timedelta(days=1)
            continue
        run = [day]
        while not free(run[-1] + datetime.timedelta(days=1)):
            run.append(run[-1] + datetime.timedelta(days=1))
        before, after = run[0] - datetime.timedelta(days=1), run[-1] + datetime.timedelta(days=1)
        # a gap counts only next to a holiday: between two plain weekends it is an ordinary week
        if len(run) <= max_days and free(before) and free(after):
            start, end = before, after
            while free(start - datetime.timedelta(days=1)):
                start -= datetime.timedelta(days=1)
            while free(end + datetime.timedelta(days=1)):
                end += datetime.timedelta(days=1)
            holidays = [{"date": d.isoformat(), "name": table[d]}
                        for d in (start + datetime.timedelta(days=i) for i in range((end - start).days + 1))
                        if d in table]
            if holidays:
                found.append({
                    "take_off": [{"date": d.isoformat(), "weekday_de": WEEKDAYS_DE[d.weekday()]} for d in run],
                    "days_off_needed": len(run),
                    "free_from": start.isoformat(),
                    "free_until": end.isoformat(),
                    "free_days": (end - start).days + 1,
                    "holidays": holidays,
                })
        day = run[-1] + datetime.timedelta(days=1)
    return {"year": year, "max_days": max_days, "holidays_of": _scope(state),
            "count": len(found), "bridges": found}


# --- meeting_times -----------------------------------------------------------

def _clock(value: Any, name: str, default: str) -> datetime.time:
    text = value.strip() if isinstance(value, str) and value.strip() else default
    try:
        return datetime.time.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{name} must be HH:MM, got {value!r}") from None


def meeting_times(args: Dict[str, Any]) -> Dict[str, Any]:
    zones_arg = args.get("timezones")
    if not isinstance(zones_arg, list) or not zones_arg:
        raise ValueError("timezones must be a non-empty list of IANA names")
    if len(zones_arg) > MAX_ZONES:
        raise ValueError(f"at most {MAX_ZONES} time zones per call")
    source = _zone(args.get("timezone"))
    zones = [source] + [z for z in (_zone(v) for v in zones_arg) if str(z) != str(source)]
    day = _today(args)
    work_start = _clock(args.get("work_start"), "work_start", "09:00")
    work_end = _clock(args.get("work_end"), "work_end", "17:00")
    if work_end <= work_start:
        raise ValueError("work_end must be after work_start")

    def window(zone: ZoneInfo) -> Tuple[datetime.datetime, datetime.datetime]:
        return (datetime.datetime.combine(day, work_start, zone).astimezone(UTC),
                datetime.datetime.combine(day, work_end, zone).astimezone(UTC))

    out: Dict[str, Any] = {"date": day.isoformat(), "timezone": str(source),
                           "working_hours": f"{work_start:%H:%M}-{work_end:%H:%M} local time in every zone"}
    moment = None
    if args.get("time"):
        clock = _clock(args.get("time"), "time", "00:00")
        moment = datetime.datetime.combine(day, clock, source)
    rows = []
    for zone in zones:
        start, end = window(zone)
        row: Dict[str, Any] = {"timezone": str(zone),
                               "utc_offset": datetime.datetime.combine(day, datetime.time(12), zone).strftime("%z")}
        if moment is not None:
            local = moment.astimezone(zone)
            local_start = datetime.datetime.combine(local.date(), work_start, zone)
            local_end = datetime.datetime.combine(local.date(), work_end, zone)
            row["local"] = local.isoformat()
            row["weekday_de"] = WEEKDAYS_DE[local.weekday()]
            row["in_working_hours"] = local.weekday() < 5 and local_start <= local < local_end
        row["weekend"] = day.weekday() >= 5
        rows.append((row, start, end))
    out["zones"] = [r for r, _, _ in rows]
    common_start = max(s for _, s, _ in rows)
    common_end = min(e for _, _, e in rows)
    if day.weekday() >= 5:
        out["overlap"] = None
        out["note"] = f"{day.isoformat()} is a {WEEKDAYS_EN[day.weekday()]}"
    elif common_start < common_end:
        out["overlap"] = {
            "minutes": int((common_end - common_start).total_seconds() // 60),
            "utc": f"{common_start:%H:%M}-{common_end:%H:%M}",
            "local": {str(z): f"{common_start.astimezone(z):%H:%M}-{common_end.astimezone(z):%H:%M}" for z in zones},
        }
    else:
        out["overlap"] = None
        out["note"] = "the working hours of these zones do not overlap on this date"
    return out


# --- registration ------------------------------------------------------------

_DATE_REF = {"type": "string", "description": "Reference date as YYYY-MM-DD; empty means today."}
_TZ = {"type": "string", "description": "IANA time zone such as Europe/Berlin; empty means the server's local zone."}

TOOLS = [
    Tool(
        name="period_bounds",
        description=(
            "First and last day of a period relative to today or to a date: today, yesterday, tomorrow, "
            "this/last/next week (ISO, Monday to Sunday), month, quarter, half year or year, the n days "
            "ending or starting on the date (last_days, next_days, both include the date), or an explicit "
            "month, quarter, half_year or year. Returns start and end with weekday, the number of days and "
            "working days, and the German public holidays in it. Use it for \"last week\", \"Vormonat\", "
            "\"Q3\" and the like instead of working the dates out."
        ),
        inputSchema={"type": "object", "properties": {
            "period": {"type": "string", "enum": list(PERIODS)},
            "date": _DATE_REF,
            "days": {"type": "integer", "description": "Number of days for last_days and next_days."},
            "year": {"type": "integer", "description": "Year for month, quarter, half_year and year."},
            "month": {"type": "integer", "description": "Month 1 to 12 for period month."},
            "quarter": {"type": "integer", "description": "Quarter 1 to 4 for period quarter."},
            "half_year": {"type": "integer", "description": "Half year 1 or 2 for period half_year."},
            "state": _STATE_PROP,
        }, "required": ["period"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="date_diff",
        description=(
            "Distance from start to end: calendar days, weeks and days, years/months/days (a month added "
            "to the 31st ends on the last day of a shorter month), and working days counted after start up "
            "to and including end (so add_days with that many working days leads from start to end). "
            "With a time in start or end also the elapsed time in seconds, hours and as ISO duration, "
            "across daylight saving changes. Negative when end lies before start."
        ),
        inputSchema={"type": "object", "properties": {
            "start": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS] with optional offset."},
            "end": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS] with optional offset."},
            "timezone": _TZ,
            "state": _STATE_PROP,
        }, "required": ["start", "end"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="nth_weekday",
        description=(
            "The n-th weekday of a month (year, month, n; n=-1 is the last, -2 the second to last), or the "
            "n-th such weekday after a date (date, n>0) or before it (n<0), the date itself not counted. "
            "Returns the date with weekday, ISO week, holiday and working day; in month mode also every "
            "date of that weekday in the month. Weekday names in English or German."
        ),
        inputSchema={"type": "object", "properties": {
            "weekday": {"type": "string", "description": "Monday to Sunday or Montag to Sonntag."},
            "n": {"type": "integer", "description": "1 is the first, -1 the last; never 0."},
            "year": {"type": "integer"},
            "month": {"type": "integer", "description": "1 to 12."},
            "date": {"type": "string", "description": "YYYY-MM-DD; leave out with year and month."},
            "state": _STATE_PROP,
        }, "required": ["weekday", "n"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="convert_timestamp",
        description=(
            "Converts a timestamp into UTC and local time and into every other form: Unix seconds, Unix "
            "milliseconds, Excel serial (1900 date system, days with the time as fraction) and ISO 8601. "
            "Pass the kind of the value; a 13-digit Unix value is milliseconds. Excel serials and ISO "
            "times without offset are read as local time in timezone."
        ),
        inputSchema={"type": "object", "properties": {
            "value": {"type": ["number", "string"], "description": "The timestamp."},
            "kind": {"type": "string", "enum": list(TIMESTAMP_KINDS)},
            "timezone": _TZ,
        }, "required": ["value", "kind"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="iso_duration",
        description=(
            "Reads an ISO 8601 duration (P1Y2M3DT4H5M6S, PT90M, P2W, -P1D) into its parts, German text and "
            "total seconds and hours, or turns a number of seconds into an ISO duration. With start it adds "
            "the duration to that date or time: years and months by calendar, days by date, hours and "
            "smaller as elapsed time."
        ),
        inputSchema={"type": "object", "properties": {
            "value": {"type": ["string", "number"], "description": "ISO 8601 duration or seconds."},
            "start": {"type": "string", "description": "Optional YYYY-MM-DD or YYYY-MM-DDTHH:MM to add the duration to."},
            "timezone": _TZ,
        }, "required": ["value"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="bridge_days",
        description=(
            "Bridge days (Brückentage) of a year: working days, at most max_days in a row, between a "
            "public holiday and a weekend or another holiday. For each the days to take off, the free "
            "block it gives (from, until, number of days) and its holidays."
        ),
        inputSchema={"type": "object", "properties": {
            "year": {"type": "integer"},
            "max_days": {"type": "integer", "description": "Longest gap of working days, 1 to 3; default 1."},
            "state": _STATE_PROP,
        }, "required": ["year"]},
        annotations=_READ_ONLY,
    ),
    Tool(
        name="meeting_times",
        description=(
            "A meeting time in several time zones and the overlap of their working hours on a date. With "
            "time (HH:MM in timezone) every zone gets its local time, weekday and whether it lies in its "
            "working hours. Always returns the common window of working hours (default 09:00 to 17:00 "
            "local time in each zone) in UTC and in every zone. Public holidays abroad are not known."
        ),
        inputSchema={"type": "object", "properties": {
            "timezones": {"type": "array", "items": {"type": "string"},
                          "description": f"IANA time zones, at most {MAX_ZONES}."},
            "timezone": {"type": "string", "description": "Zone of time and date; empty means the server's local zone."},
            "date": _DATE_REF,
            "time": {"type": "string", "description": "Optional HH:MM in timezone."},
            "work_start": {"type": "string", "description": "Start of working hours, default 09:00."},
            "work_end": {"type": "string", "description": "End of working hours, default 17:00."},
        }, "required": ["timezones"]},
        annotations=_READ_ONLY,
    ),
]

HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "period_bounds": period_bounds,
    "date_diff": date_diff,
    "nth_weekday": nth_weekday,
    "convert_timestamp": convert_timestamp,
    "iso_duration": iso_duration,
    "bridge_days": bridge_days,
    "meeting_times": meeting_times,
}
