"""MCP 协议冒烟测试：启动本地服务器并模拟小智客户端的调用流程。

覆盖: initialize -> tools/list -> tools/call(search_song) ->
      tools/call(play_song) -> resources/read(ResourceLink)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 测试脚本自身输出使用 UTF-8，避免 Windows 控制台 GBK 报错
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


class MCPClient:
    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self._id = 0

    async def send(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        self._id += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if not notify:
            msg["id"] = self._id
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        line = await asyncio.get_running_loop().run_in_executor(None, self.proc.stdout.readline)
        if not line:
            raise RuntimeError("服务器 stdout 已关闭")
        return json.loads(line)


async def main() -> int:
    # PowerShell 5.1 传中文参数会乱码，优先使用环境变量
    query = os.environ.get("SMOKE_QUERY") or (sys.argv[1] if len(sys.argv) > 1 else "青花瓷")
    query = query.encode("utf-8", errors="ignore").decode("utf-8")
    env = os.environ.copy()
    env.setdefault("MUSIC_SOURCES", "kuwo,netease")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "music_mcp"],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    client = MCPClient(proc)
    try:
        init = await client.send(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}},
        )
        print("initialize:", json.dumps(init, ensure_ascii=False)[:300])
        assert init["result"]["serverInfo"]["name"] == "xiaozhi-music-mcp"

        await client.send("notifications/initialized", {}, notify=True)

        tools = await client.send("tools/list")
        names = [t["name"] for t in tools["result"]["tools"]]
        print("tools:", names)
        assert "search_song" in names and "play_song" in names

        search = await client.send("tools/call", {"name": "search_song", "arguments": {"query": query, "limit": 3}})
        print("search_song result:", json.dumps(search, ensure_ascii=False)[:600])
        assert "error" not in search

        play = await client.send("tools/call", {"name": "play_song", "arguments": {"query": query}})
        print("play_song result:", json.dumps(play, ensure_ascii=False)[:600])
        assert "error" not in play
        link = next((c for c in play["result"]["content"] if c.get("type") == "resource_link"), None)
        if link:
            url = link.get("description")
            read = await client.send(
                "resources/read",
                {
                    "uri": "resource://read_from_http",
                    "arguments": {"url": url, "start": 0, "end": 4096},
                },
            )
            print("resources/read:", json.dumps(read, ensure_ascii=False)[:400])
            assert "error" not in read
            blob = read["result"]["contents"][0]["blob"]
            print(f"音频块 base64 长度: {len(blob)}")
        else:
            print("未返回 ResourceLink（可能所有音源均失败）")

        print("\nSMOKE OK")
        return 0
    finally:
        proc.terminate()
        try:
            err = proc.stderr.read()
            if err:
                print("\n--- server stderr ---\n" + err[-2000:])
        except Exception:
            pass
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
