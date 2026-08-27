# time-mcp-http

The official [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
`time` server (`get_current_time`, `convert_time`) re-hosted over streamable
HTTP instead of stdio — so it can run as a plain Docker service reachable
over HTTP, instead of needing LibreChat to spawn a local subprocess.

The tool logic (timezone math, schemas) is imported straight from the
installed `mcp-server-time` package (`TimeServer`/`TimeTools`) — only the
transport is different, so `pip install --upgrade mcp-server-time` still
picks up upstream fixes.

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
