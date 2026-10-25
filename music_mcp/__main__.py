"""入口：python -m music_mcp"""

from __future__ import annotations

import asyncio
import logging
import sys

from music_mcp.app import build_server
from music_mcp.config import settings
from music_mcp.utils import setup_logging


def main() -> int:
    setup_logging(settings.log_level)
    logger = logging.getLogger("music_mcp")
    logger.info("小智音乐 MCP 启动，音源: %s", settings.enabled_sources)
    server = build_server()
    try:
        asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
