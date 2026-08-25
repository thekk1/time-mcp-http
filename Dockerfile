# syntax=docker/dockerfile:1
# time-mcp-http — the official modelcontextprotocol/servers "time" tool
# logic (mcp-server-time), re-hosted over streamable HTTP. No Exchange/EWS
# involved; this is a standalone, general-purpose MCP utility server.

FROM python:3.11-slim AS builder
WORKDIR /src
COPY pyproject.toml ./
COPY time_mcp_http ./time_mcp_http
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .

FROM python:3.11-slim
RUN groupadd -r mcp && useradd -r -g mcp -d /home/mcp -m mcp
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TIME_MCP_HOST=0.0.0.0 \
    TIME_MCP_PORT=8080
RUN python -c "import time_mcp_http.main"
USER mcp
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=3).status==200 else 1)"
CMD ["time-mcp-http"]
