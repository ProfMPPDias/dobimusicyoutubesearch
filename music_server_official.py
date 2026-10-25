"""小智AI免费音乐MCP服务器 - STDIO实现。

协议：MCP (Model Context Protocol) 2024-11-05，STDIO 传输。
从 stdin 读取 JSON-RPC 2.0 请求行，处理结果写入 stdout（日志走 stderr）。
可用于 ModelScope 魔搭社区 MCP 托管部署（command: uvx xiaozhi-music-mcp）。

音乐数据源：飞飞免费API「点歌台 - 网易云音乐」(https://ffapi.cn/int/v1/dg_netease)
- 搜索/详情/歌词/播放地址均为免费接口，无需 key（VIP 歌曲需 cookie，可选）。
"""

import asyncio
import json
import logging
import sys
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROTOCOL_VERSION = "2024-11-05"
API_BASE = "https://ffapi.cn/int/v1/dg_netease"

logger = logging.getLogger("xiaozhi-music-mcp")
logger.setLevel(logging.INFO)
_stderr_handler = logging.StreamHandler(sys.stderr)  # 日志只走 stderr，不污染 stdout
_stderr_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_stderr_handler)

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 播放状态（进程内共享）
playback_state: Dict[str, Any] = {
    "is_playing": False,
    "current_song": None,
    "volume": 50,
    "position": 0,
    "playlist": [],
}


# ---------------------------------------------------------------------------
# 飞飞 API 封装
# ---------------------------------------------------------------------------

def _ffapi_sync(params: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    """同步调用 dg_netease 接口（由 asyncio.to_thread 包装，不阻塞事件循环）。"""
    url = API_BASE + "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"code": -1, "msg": f"响应不是合法 JSON: {raw[:120]}"}


async def _ffapi(params: Dict[str, Any]) -> Dict[str, Any]:
    return await asyncio.to_thread(_ffapi_sync, params)


async def _search(query: str, limit: int) -> List[Dict[str, Any]]:
    """搜索歌曲，返回 [{n, title, singer, pic}]。"""
    result = await _ffapi({"msg": query, "limit": min(max(limit, 1), 50), "format": "json"})
    if result.get("code") != 200:
        raise RuntimeError(f"搜索失败: {result.get('msg', '未知错误')}")
    return result.get("data") or []


async def _song_detail(query: str, n: int) -> Dict[str, Any]:
    """选歌详情（含歌曲 id）。"""
    result = await _ffapi({"msg": query, "n": n, "format": "json"})
    if result.get("code") != 200 or not isinstance(result.get("data"), dict):
        raise RuntimeError(f"获取歌曲详情失败: {result.get('msg', '未知错误')}")
    return result["data"]


async def _music_url(song_id: Any) -> str:
    """按歌曲 id 获取真实播放地址（网易云 CDN m4a，带时效签名）。"""
    result = await _ffapi({"act": "musicurl", "format": "json", "id": song_id})
    if result.get("code") != 200:
        raise RuntimeError(f"获取播放地址失败: {result.get('msg', '未知错误')}")
    url = result.get("url")
    if not url:
        raise RuntimeError("该歌曲没有可用的免费播放地址（可能需要 VIP）")
    return url


async def _lyrics(song_id: Any) -> str:
    """按歌曲 id 获取 LRC 歌词（接口直接返回纯文本 LRC，不套 JSON）。"""
    url = API_BASE + "?" + urllib.parse.urlencode({"act": "lrcgc", "id": song_id, "format": "json"})
    req = urllib.request.Request(url, headers=_UA)

    def _fetch() -> str:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "replace")
        stripped = raw.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                return raw
            if obj.get("code") != 200:
                raise RuntimeError(f"获取歌词失败: {obj.get('msg', '未知错误')}")
            return str(obj.get("lrc") or obj.get("data") or raw)
        return raw  # 纯文本 LRC

    return await asyncio.to_thread(_fetch)


# ---------------------------------------------------------------------------
# MCP 服务器框架
# ---------------------------------------------------------------------------

class MCPServer:
    """标准 MCP STDIO 服务器。"""

    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version
        self.tools: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []

    def add_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        self.tools.append(
            {"name": name, "description": description, "inputSchema": input_schema, "handler": handler}
        )

    def add_resource(self, uri: str, name: str, description: str = "") -> None:
        self.resources.append({"uri": uri, "name": name, "description": description})

    def handle_initialize(self) -> Dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {"name": self.name, "version": self.version},
        }

    def handle_tools_list(self) -> Dict[str, Any]:
        return {
            "tools": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"],
                }
                for t in self.tools
            ]
        }

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        for tool in self.tools:
            if tool["name"] == name:
                try:
                    text = await tool["handler"](arguments)
                    return {"content": [{"type": "text", "text": str(text)}], "isError": False}
                except Exception as exc:  # noqa: BLE001
                    logger.exception("tool %s failed", name)
                    return {
                        "content": [{"type": "text", "text": f"工具执行失败: {exc}"}],
                        "isError": True,
                    }
        return {"content": [{"type": "text", "text": f"未知工具: {name}"}], "isError": True}

    def handle_resources_list(self) -> Dict[str, Any]:
        return {
            "resources": [
                {"uri": r["uri"], "name": r["name"], "description": r["description"]}
                for r in self.resources
            ]
        }

    def handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        uri = params.get("uri", "")
        if uri == "music://current_playlist":
            text = self._playlist_text()
        elif uri == "music://current_playing":
            text = self._playing_text()
        else:
            raise ValueError(f"未知资源: {uri}")
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]}

    def _playlist_text(self) -> str:
        playlist = playback_state["playlist"]
        if not playlist:
            return "播放列表为空"
        lines = ["当前播放列表:", ""]
        for i, song in enumerate(playlist, 1):
            lines.append(f"{i}. {song['name']} - {song['artist']}")
        return "\n".join(lines)

    def _playing_text(self) -> str:
        current = playback_state["current_song"]
        if not current:
            return "当前没有播放歌曲"
        status = "播放中" if playback_state["is_playing"] else "已暂停"
        return (
            f"当前播放: {current['name']} - {current['artist']}\n"
            f"状态: {status}\n音量: {playback_state['volume']}%"
        )


# ---------------------------------------------------------------------------
# 工具处理函数
# ---------------------------------------------------------------------------

async def search_music_handler(arguments: Dict[str, Any]) -> str:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ValueError("query 不能为空")
    limit = int(arguments.get("limit", 10))
    songs = await _search(query, limit)
    if not songs:
        return f"没有找到与 '{query}' 相关的歌曲"
    lines = [f"搜索 '{query}' 的结果：", ""]
    for song in songs:
        lines.append(f"{song.get('n')}. {song.get('title')} - {song.get('singer')}")
    lines.append("")
    lines.append(f"共 {len(songs)} 首。要播放哪一首请告诉我序号。")
    return "\n".join(lines)


async def play_music_handler(arguments: Dict[str, Any]) -> str:
    """播放歌曲：优先按 song_id 精确播放；否则按 query 搜索取第一首。"""
    song_id = arguments.get("song_id")
    query = str(arguments.get("query", "")).strip()
    song_name = str(arguments.get("song_name", "")).strip()
    artist = str(arguments.get("artist", "")).strip()

    if song_id:
        pass  # 用传入的 id
    elif query:
        songs = await _search(query, 5)
        if not songs:
            return f"没有找到与 '{query}' 相关的歌曲"
        first = songs[0]
        detail = await _song_detail(query, int(first["n"]))
        song_id = detail.get("id")
        song_name = song_name or detail.get("name") or first.get("title", "")
        artist = artist or detail.get("singer") or first.get("singer", "")
    else:
        raise ValueError("需要提供 song_id 或 query")

    url = await _music_url(song_id)
    playback_state["current_song"] = {
        "id": str(song_id),
        "name": song_name or str(song_id),
        "artist": artist or "未知歌手",
        "url": url,
    }
    playback_state["is_playing"] = True
    playback_state["position"] = 0

    return (
        f"正在播放: {playback_state['current_song']['name']} - {playback_state['current_song']['artist']}\n"
        f"播放地址: {url}\n"
        f"(地址有时效，请尽快使用)"
    )


async def get_music_url_handler(arguments: Dict[str, Any]) -> str:
    song_id = arguments.get("song_id")
    if not song_id:
        raise ValueError("song_id 不能为空")
    url = await _music_url(song_id)
    return f"播放地址: {url}\n(地址有时效，请尽快使用)"


async def get_lyrics_handler(arguments: Dict[str, Any]) -> str:
    song_id = arguments.get("song_id")
    if not song_id:
        raise ValueError("song_id 不能为空")
    lrc = await _lyrics(song_id)
    return f"歌词:\n{lrc}"


async def pause_music_handler(arguments: Dict[str, Any]) -> str:
    playback_state["is_playing"] = False
    return "音乐已暂停"


async def resume_music_handler(arguments: Dict[str, Any]) -> str:
    playback_state["is_playing"] = True
    current = playback_state["current_song"]
    return f"继续播放: {current['name']} - {current['artist']}" if current else "没有可继续播放的歌曲"


async def stop_music_handler(arguments: Dict[str, Any]) -> str:
    playback_state["is_playing"] = False
    playback_state["current_song"] = None
    playback_state["position"] = 0
    return "音乐已停止"


async def set_volume_handler(arguments: Dict[str, Any]) -> str:
    volume = max(0, min(100, int(arguments.get("volume", 50))))
    playback_state["volume"] = volume
    return f"音量已设置为: {volume}%"


async def add_to_playlist_handler(arguments: Dict[str, Any]) -> str:
    song = {
        "id": str(arguments.get("song_id", "")),
        "name": str(arguments.get("song_name", "未知歌曲")),
        "artist": str(arguments.get("artist", "未知歌手")),
    }
    playback_state["playlist"].append(song)
    return f"已添加到播放列表: {song['name']} - {song['artist']}"


async def get_playlist_handler(arguments: Dict[str, Any]) -> str:
    return server._playlist_text()  # noqa: SLF001 - 单进程实例


async def clear_playlist_handler(arguments: Dict[str, Any]) -> str:
    count = len(playback_state["playlist"])
    playback_state["playlist"].clear()
    return f"已清空播放列表（共 {count} 首）"


async def next_song_handler(arguments: Dict[str, Any]) -> str:
    playlist = playback_state["playlist"]
    if not playlist:
        return "播放列表为空，无法切歌"
    current = playback_state["current_song"]
    if current:
        try:
            idx = next(i for i, s in enumerate(playlist) if s["id"] == current["id"])
            nxt = playlist[(idx + 1) % len(playlist)]
        except StopIteration:
            nxt = playlist[0]
    else:
        nxt = playlist[0]
    playback_state["current_song"] = nxt
    playback_state["is_playing"] = True
    return f"下一首: {nxt['name']} - {nxt['artist']}"


async def previous_song_handler(arguments: Dict[str, Any]) -> str:
    playlist = playback_state["playlist"]
    if not playlist:
        return "播放列表为空，无法切歌"
    current = playback_state["current_song"]
    if current:
        try:
            idx = next(i for i, s in enumerate(playlist) if s["id"] == current["id"])
            prev = playlist[(idx - 1) % len(playlist)]
        except StopIteration:
            prev = playlist[0]
    else:
        prev = playlist[-1]
    playback_state["current_song"] = prev
    playback_state["is_playing"] = True
    return f"上一首: {prev['name']} - {prev['artist']}"


# ---------------------------------------------------------------------------
# 注册工具 / 资源
# ---------------------------------------------------------------------------

server = MCPServer("xiaozhi-music-mcp", "1.1.0")

server.add_tool(
    "search_music",
    "搜索音乐（网易云音乐源），支持按歌曲名、歌手名搜索",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词（歌曲名、歌手）"},
            "limit": {"type": "integer", "description": "返回结果数量", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
    },
    search_music_handler,
)
server.add_tool(
    "play_music",
    "播放音乐，返回真实播放地址。提供 query（歌名/歌手）自动搜索并播放第一首，或提供 song_id 精确播放",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "歌曲名或歌手名（与 song_id 二选一）"},
            "song_id": {"type": "string", "description": "网易云歌曲ID（与 query 二选一）"},
            "song_name": {"type": "string", "description": "歌曲名称（可选，显示用）"},
            "artist": {"type": "string", "description": "歌手名称（可选，显示用）"},
        },
    },
    play_music_handler,
)
server.add_tool(
    "play_song",
    "播放音乐（play_music 的别名）",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "歌曲名或歌手名"},
            "song_id": {"type": "string", "description": "歌曲ID"},
        },
    },
    play_music_handler,
)
server.add_tool(
    "search_song",
    "搜索音乐（search_music 的别名）",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    },
    search_music_handler,
)
server.add_tool(
    "get_music_url",
    "获取指定歌曲的播放地址",
    {
        "type": "object",
        "properties": {"song_id": {"type": "string", "description": "网易云歌曲ID"}},
        "required": ["song_id"],
    },
    get_music_url_handler,
)
server.add_tool(
    "get_lyrics",
    "获取指定歌曲的LRC歌词",
    {
        "type": "object",
        "properties": {"song_id": {"type": "string", "description": "网易云歌曲ID"}},
        "required": ["song_id"],
    },
    get_lyrics_handler,
)
server.add_tool("pause_music", "暂停当前播放的音乐", {"type": "object", "properties": {}}, pause_music_handler)
server.add_tool("resume_music", "继续播放已暂停的音乐", {"type": "object", "properties": {}}, resume_music_handler)
server.add_tool("stop_music", "停止播放音乐", {"type": "object", "properties": {}}, stop_music_handler)
server.add_tool(
    "set_volume",
    "设置音乐播放音量",
    {
        "type": "object",
        "properties": {"volume": {"type": "integer", "description": "音量百分比 0-100", "minimum": 0, "maximum": 100}},
        "required": ["volume"],
    },
    set_volume_handler,
)
server.add_tool(
    "add_to_playlist",
    "将歌曲添加到播放列表",
    {
        "type": "object",
        "properties": {
            "song_id": {"type": "string", "description": "网易云歌曲ID"},
            "song_name": {"type": "string", "description": "歌曲名称"},
            "artist": {"type": "string", "description": "歌手名称"},
        },
        "required": ["song_id"],
    },
    add_to_playlist_handler,
)
server.add_tool("get_playlist", "获取当前播放列表", {"type": "object", "properties": {}}, get_playlist_handler)
server.add_tool("clear_playlist", "清空播放列表", {"type": "object", "properties": {}}, clear_playlist_handler)
server.add_tool("next_song", "播放下一首歌", {"type": "object", "properties": {}}, next_song_handler)
server.add_tool("previous_song", "播放上一首歌", {"type": "object", "properties": {}}, previous_song_handler)

server.add_resource("music://current_playlist", "当前播放列表", "显示当前的音乐播放列表")
server.add_resource("music://current_playing", "当前播放", "显示当前正在播放的歌曲信息")


# ---------------------------------------------------------------------------
# STDIO 事件循环
# ---------------------------------------------------------------------------

async def _handle_message(server: MCPServer, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}

    try:
        if method == "initialize":
            result = server.handle_initialize()
        elif method == "notifications/initialized":
            logger.info("client initialized")
            return None
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = server.handle_tools_list()
        elif method == "tools/call":
            result = await server.handle_tools_call(params)
        elif method == "resources/list":
            result = server.handle_resources_list()
        elif method == "resources/read":
            result = server.handle_resources_read(params)
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"未知方法: {method}"},
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("method %s failed", method)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32603, "message": f"内部错误: {exc}"},
        }

    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


async def _run_stdio(server: MCPServer) -> None:
    loop = asyncio.get_event_loop()
    logger.info("xiaozhi-music-mcp STDIO server started (netease source)")
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.error("invalid JSON: %s", exc)
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON解析错误"}}) + "\n")
            sys.stdout.flush()
            continue
        response = await _handle_message(server, message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    logger.info("stdin closed, exiting")


def main() -> None:
    try:
        asyncio.run(_run_stdio(server))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
