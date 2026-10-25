"""共享测试夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class StdioHarness:
    """直接以内存管道方式驱动 MCPServer，避免子进程开销。"""

    def __init__(self, server):
        self.server = server
        self._id = 0
        self.responses = []

    async def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        return await self.server._dispatch(msg)


@pytest.fixture
def harness_factory():
    def make(server):
        return StdioHarness(server)

    return make
