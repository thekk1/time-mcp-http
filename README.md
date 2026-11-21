# time-mcp-http

The official [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
`time` server (`get_current_time`, `convert_time`) re-hosted over streamable
HTTP instead of stdio — so it can run as a plain Docker service reachable
over HTTP, instead of needing LibreChat to spawn a local subprocess.

The tool logic (timezone math, schemas) is imported straight from the
installed `mcp-server-time` package (`TimeServer`/`TimeTools`) — only the
transport is different, so `pip install --upgrade mcp-server-time` still
picks up upstream fixes.

## Calendar tools

Next to the upstream tools the server has its own calendar tools
(`time_mcp_http/calendar_tools.py`), so a model never works out these facts in
its head:

| Tool | Returns |
|---|---|
| `date_info` | weekday (English and German), ISO week, day of the year, German public holiday, working day |
| `date_range` | every day of a period (at most 366) with these facts, number of days and working days, the holidays in it |
| `add_days` | the date n calendar days or n working days after (or before) a date |
| `calendar_week` | ISO week (Kalenderwoche) and year to Monday and Sunday, or a date to its week |
| `list_holidays` | all German public holidays of a year |
| `dst_transitions` | the daylight saving time changes of a time zone in a year |
| `leap_seconds` | all leap seconds, TAI minus UTC, and until when the list is valid |

Date arithmetic (`time_mcp_http/period_tools.py`):

| Tool | Returns |
|---|---|
| `period_bounds` | first and last day of today, yesterday, this/last/next week, month, quarter, half year or year, the last or next n days, or an explicit month, quarter, half year or year |
| `date_diff` | days, weeks, years/months/days and working days between two dates; with times the elapsed time across DST changes |
| `nth_weekday` | the n-th (or last) weekday of a month, or the n-th weekday after or before a date |
| `convert_timestamp` | Unix seconds or milliseconds, Excel serials and ISO 8601 into each other, in UTC and local time |
| `iso_duration` | an ISO 8601 duration into parts, German text and seconds, seconds into a duration, or a duration added to a date |
| `bridge_days` | the bridge days (Brückentage) of a year with the free block each gives |
| `meeting_times` | a meeting time in several time zones and the overlap of their working hours |

Holidays come from the [`holidays`](https://pypi.org/project/holidays/)
package. Without `state` only the holidays that apply in all of Germany count;
a two-letter state code (`NW`, `BY`, …) adds that state's holidays. Leap
seconds come from `/usr/share/zoneinfo/leap-seconds.list` of the base image's
tzdata (override with `LEAP_SECONDS_FILE`), so there is no network access.

## Why this exists

A calling assistant has no built-in sense of "now" — it can misread an
ISO timestamp's UTC offset, or simply not know what day it is. Giving it
an explicit, callable, on-demand tool is more reliable than trying to
inject ambient date/time into every system prompt (LibreChat's Agents
endpoint doesn't support that natively as of 2026-08).

## Run

```
docker build -t time-mcp-http .
docker run --rm -p 8080:8080 -e LOCAL_TIMEZONE=Europe/Berlin time-mcp-http
```

`LOCAL_TIMEZONE` (IANA name, e.g. `Europe/Berlin`) only fills in the
tool-description text ("use this as local timezone if the user doesn't
specify one") — every call still takes an explicit `timezone` argument.
If unset or invalid, it falls back to `UTC` rather than failing to boot.

No credentials, no per-user state, no `MCP_API_KEY` — deliberately: a 401
from any gate makes LibreChat's non-OAuth MCP client try (and get stuck
on) OAuth. Docker network isolation is the boundary here, not an API key.

## Test

```
pip install -e '.[dev]'
LOCAL_TIMEZONE=Europe/Berlin pytest
```
