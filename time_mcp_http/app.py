"""Streamable-HTTP transport for the official mcp-server-time tool logic.

The upstream package (modelcontextprotocol/servers, src/time) only ships a
stdio entrypoint (``serve()`` in ``mcp_server_time.server`` builds a
``Server`` and immediately runs it over stdio — the tool handlers are local
closures, not importable). Rather than fork the tool logic, this module
re-registers the SAME schemas against the SAME ``TimeServer``/``TimeTools``
from the installed package and only swaps the transport, so
`pip install --upgrade mcp-server-time` still picks up upstream fixes.

No credentials, no per-user state, no auth gate: this is a stateless,
read-only utility (current time / timezone conversion, plus the calendar
facts in calendar_tools), deliberately with
no MCP_API_KEY -- a 401 from ANY gate makes LibreChat's non-OAuth MCP
client try OAuth and get stuck.
"""

import contextlib
import logging
import os
from typing import Any, Dict, List, Sequence

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool, ToolAnnotations
from mcp_server_time.server import TimeServer, TimeTools, get_local_tz

from time_mcp_http import calendar_tools
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route, Router

logger = logging.getLogger(__name__)

_time_server = TimeServer()
try:
    # Cosmetic only (goes into the tool-description text below so the model
    # has a sane default to reach for) — must never block boot. A minimal
    # container image commonly has no /etc/localtime, and tzlocal's
    # autodetection can return a bare abbreviation ("CEST") that ZoneInfo
    # rejects; LOCAL_TIMEZONE should be set explicitly in production
    # (see the docker-compose snippet in README.md), but a bad or
    # missing value degrades to UTC instead of crashing the process.
    _local_tz = str(get_local_tz(os.environ.get("LOCAL_TIMEZONE") or None))
except Exception:
    logger.warning("could not determine local timezone, defaulting to UTC — "
                    "set LOCAL_TIMEZONE explicitly")
    _local_tz = "UTC"


def build_server() -> Server:
    server = Server("time-mcp-http")

    @server.list_tools()
    async def list_tools() -> List[Tool]:
        return [
            Tool(
                name=TimeTools.GET_CURRENT_TIME.value,
                description="Get current time in a specific timezone",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timezone": {
                            "type": "string",
                            "description": (
                                "IANA timezone name (e.g., 'America/New_York', "
                                f"'Europe/London'). Use '{_local_tz}' as local "
                                "timezone if no timezone provided by the user."
                            ),
                        }
                    },
                    "required": ["timezone"],
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False,
                    idempotentHint=True, openWorldHint=False,
                ),
            ),
            Tool(
                name=TimeTools.CONVERT_TIME.value,
                description="Convert time between timezones",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source_timezone": {
                            "type": "string",
                            "description": (
                                "Source IANA timezone name. Use "
                                f"'{_local_tz}' as local timezone if none given."
                            ),
                        },
                        "time": {
                            "type": "string",
                            "description": "Time to convert, 24-hour format (HH:MM)",
                        },
                        "target_timezone": {
                            "type": "string",
                            "description": (
                                "Target IANA timezone name. Use "
                                f"'{_local_tz}' as local timezone if none given."
                            ),
                        },
                    },
                    "required": ["source_timezone", "time", "target_timezone"],
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False,
                    idempotentHint=True, openWorldHint=False,
                ),
            ),
            *calendar_tools.TOOLS,
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: Dict[str, Any]
    ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        import json

        if name in calendar_tools.HANDLERS:
            try:
                out = calendar_tools.HANDLERS[name](arguments or {})
            except Exception as exc:
                raise ValueError(f"Error processing calendar query: {exc}") from exc
            return [TextContent(type="text", text=json.dumps(out, indent=2, ensure_ascii=False))]

        try:
            if name == TimeTools.GET_CURRENT_TIME.value:
                timezone = arguments.get("timezone")
                if not timezone:
                    raise ValueError("Missing required argument: timezone")
                result = _time_server.get_current_time(timezone)
            elif name == TimeTools.CONVERT_TIME.value:
                if not all(k in arguments for k in
                           ("source_timezone", "time", "target_timezone")):
                    raise ValueError("Missing required arguments")
                result = _time_server.convert_time(
                    arguments["source_timezone"], arguments["time"],
                    arguments["target_timezone"],
                )
            else:
                raise ValueError(f"Unknown tool: {name}")
        except Exception as exc:
            raise ValueError(f"Error processing time query: {exc}") from exc

        return [TextContent(type="text", text=json.dumps(result.model_dump(), indent=2))]

    return server


class _MCPEndpoint:
    """A plain function endpoint gets wrapped by Starlette as
    ``func(request) -> Response`` (see ``Route.__init__``: it only treats
    a *class* instance as raw ASGI). This class exists purely so ``Route``
    dispatches (scope, receive, send) straight through, unmodified — no
    ``Mount``, no prefix-match, no trailing-slash redirect. That redirect
    was tried (Mount("/mcp", ...)) and confirmed BROKEN against the real
    deployment: LibreChat's MCP client blocks redirects to private/
    reserved addresses as SSRF hardening, which is every Docker-internal
    address these servers ever have — so a bare POST /mcp must resolve
    directly, with no 307 in between, ever.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope, receive, send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


def build_app() -> Router:
    server = build_server()
    session_manager = StreamableHTTPSessionManager(
        app=server, json_response=False, stateless=True,
    )

    async def livez(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    @contextlib.asynccontextmanager
    async def lifespan(_app: Router):
        async with session_manager.run():
            logger.info("time-mcp-http up, local timezone=%s", _local_tz)
            yield

    return Router(
        routes=[
            Route("/livez", livez),
            Route("/readyz", livez),  # stateless, no upstream dependency to warm up
            Route("/mcp", _MCPEndpoint(session_manager),
                  methods=["GET", "POST", "DELETE"]),
        ],
        lifespan=lifespan,
    )
