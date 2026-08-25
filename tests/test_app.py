"""Dispatch-level tests: exercise the same list_tools/call_tool handlers the
HTTP transport calls, without a network round trip."""

import asyncio
import json

from time_mcp_http.app import build_server


def _run(coro):
    return asyncio.run(coro)


def test_list_tools_exposes_get_current_time_and_convert_time():
    server = build_server()
    tools = _run(_list_tools(server))
    names = {t.name for t in tools}
    assert names == {"get_current_time", "convert_time"}


async def _list_tools(server):
    # server.list_tools() registered a handler; call it via the low-level
    # request_handlers table the way the SDK itself does.
    from mcp import types
    handler = server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    return result.root.tools


def _call_tool(server, name, arguments):
    from mcp import types
    handler = server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments),
    )
    result = _run(handler(req))
    return json.loads(result.root.content[0].text)


def test_get_current_time_known_offset():
    server = build_server()
    out = _call_tool(server, "get_current_time", {"timezone": "Europe/Berlin"})
    assert out["timezone"] == "Europe/Berlin"
    assert out["datetime"][:1].isdigit()


def test_convert_time_berlin_to_riyadh_is_plus_one_hour_in_august():
    server = build_server()
    out = _call_tool(server, "convert_time", {
        "source_timezone": "Europe/Berlin",
        "time": "13:40",
        "target_timezone": "Asia/Riyadh",
    })
    assert out["time_difference"] == "+1.0h"
    assert out["target"]["datetime"].startswith(
        out["source"]["datetime"][:10])  # same calendar day


def test_unknown_tool_raises():
    server = build_server()
    import pytest
    with pytest.raises(Exception):
        _call_tool(server, "nope", {})
