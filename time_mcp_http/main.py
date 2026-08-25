import logging
import os

import uvicorn

from .app import build_app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    host = os.environ.get("TIME_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("TIME_MCP_PORT", "8080"))
    uvicorn.run(build_app(), host=host, port=port, log_level=None)


if __name__ == "__main__":
    main()
