"""轻量 MCP stdio 服务器。

手工实现 JSON-RPC 协议，以保证完整兼容小智生态的
ResourceLink + resources/read(arguments) 分页音频流协议。
所有日志输出到 stderr，stdout 只用于协议消息。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("music_mcp.mcp")

SUPPORTED_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class MCPServer:
    def __init__(self, server_name: str = "xiaozhi-music-mcp", version: str = "0.1.0"):
        self.server_name = server_name
        self.version = version
        self._tools: Dict[str, dict] = {}
        self._resources: Dict[str, dict] = {}
        self._handlers: Dict[str, Callable[[dict], Awaitable[Any]]] = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "completion/complete": self._handle_completion,
        }

    # ---------- 注册 ----------
    def add_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[[dict], Awaitable[dict]],
    ) -> None:
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "_handler": handler,
        }

    def add_resource(
        self,
        uri: str,
        name: str,
        handler: Callable[[str, dict], Awaitable[list]],
        mime_type: str = "audio/mpeg",
        description: str = "",
    ) -> None:
        self._resources[uri] = {
            "uri": uri,
            "name": name,
            "mimeType": mime_type,
            "description": description,
            "_handler": handler,
        }

    # ---------- 协议处理 ----------
    async def _handle_initialize(self, params: dict) -> dict:
        client_version = (params or {}).get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
        if client_version not in SUPPORTED_PROTOCOL_VERSIONS:
            client_version = DEFAULT_PROTOCOL_VERSION
        return {
            "protocolVersion": client_version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {"name": self.server_name, "version": self.version},
            "instructions": (
                "这是一个免费音乐搜索与播放 MCP 服务器。"
                "当用户要求搜索、点歌、播放歌曲时，先调用 search_song 搜索，"
                "再调用 play_song 播放；用户直接说'播放xxx'时可直接调用 play_song。"
                "play_song 返回的 ResourceLink 描述中是可播放的音频地址，"
                "可通过 resource://read_from_http 分页读取音频数据流式播放。"
            ),
        }

    async def _handle_ping(self, params: dict) -> dict:
        return {}

    async def _handle_tools_list(self, params: dict) -> dict:
        tools = [
            {k: v for k, v in t.items() if not k.startswith("_")}
            for t in self._tools.values()
        ]
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict) -> dict:
        name = (params or {}).get("name")
        arguments = (params or {}).get("arguments") or {}
        logger.info("[MCP] >>> Robô chamou ferramenta: %s | Args: %s", name, arguments)
        tool = self._tools.get(name)
        if tool is None:
            raise MCPError(-32602, f"未知工具: {name}")
        try:
            return await tool["_handler"](arguments)
        except MCPError:
            raise
        except Exception as exc:
            logger.exception("工具 %s 执行异常", name)
            raise MCPError(-32603, f"工具 {name} 执行失败: {exc}") from exc

    async def _handle_resources_list(self, params: dict) -> dict:
        resources = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in self._resources.values()
        ]
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict) -> dict:
        uri = (params or {}).get("uri")
        arguments = (params or {}).get("arguments") or {}
        logger.info("[MCP] >>> Robô requisitou streaming: %s (start=%s, end=%s)", uri, arguments.get("start"), arguments.get("end"))
        resource = self._resources.get(uri)
        if resource is None:
            raise MCPError(-32602, f"未知资源: {uri}")
        try:
            contents = await resource["_handler"](uri, arguments)
            return {"contents": contents}
        except MCPError:
            raise
        except Exception as exc:
            logger.exception("资源 %s 读取异常", uri)
            raise MCPError(-32603, f"读取资源失败: {exc}") from exc

    async def _handle_completion(self, params: dict) -> dict:
        return {"completion": {"values": [], "total": 0, "hasMore": False}}

    # ---------- JSON-RPC 分发 ----------
    async def _dispatch(self, message: dict) -> Optional[dict]:
        msg_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": "Invalid Request"}}
        if method.startswith("notifications/"):
            return None
        handler = self._handlers.get(method)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"方法不存在: {method}"},
            }
        try:
            result = await handler(message.get("params") or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except MCPError as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": exc.code, "message": exc.message, "data": exc.data}}
        except Exception as exc:
            logger.exception("处理 %s 时出错", method)
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(exc)}}

    async def run_stdio(self) -> None:
        loop = asyncio.get_running_loop()
        from music_mcp.http_streamer import start_http_streamer
        try:
            await start_http_streamer()
        except Exception as exc:
            logger.warning("[STREAMER] Falha ao iniciar streamer HTTP: %s", exc)
        logger.info("MCP stdio 服务器启动: %s v%s", self.server_name, self.version)
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("收到无法解析的消息: %.200s", line)
                continue
            response = await self._dispatch(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        logger.info("MCP stdio 服务器退出（stdin 关闭）")
