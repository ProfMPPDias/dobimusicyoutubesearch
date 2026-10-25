"""MCP 工具装配：搜索、播放、音源管理。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from music_mcp.config import settings
from music_mcp.local_player import player
from music_mcp.mcp_server import MCPServer, MCPError
from music_mcp.models import Song
from music_mcp.resource_proxy import proxy
from music_mcp.sources import manager
from music_mcp.utils import compact_json, truncate_text

logger = logging.getLogger("music_mcp.app")

SOURCE_CHOICES = ["auto", *manager.names]


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _resource_link(song: Song, url: str, mime_type: str) -> dict:
    return {
        "type": "resource_link",
        "uri": proxy.URI,
        "name": f"{song.title} - {song.artist}" if song.artist else song.title,
        "description": url,
        "mimeType": mime_type,
    }


def _song_public(song: Song) -> dict:
    return song.to_dict()


async def _verify_url(url: str) -> bool:
    """快速验证播放地址可用（Range 0-1）。"""
    if "127.0.0.1" in url or "192.168." in url or "localhost" in url or "googlevideo.com" in url or "youtube" in url:
        return True
    try:
        ok = await proxy.verify_url(url)
        return ok
    except Exception as exc:
        logger.debug("播放地址验证失败 %s: %s", url, exc)
        return False


def _tool_result(
    texts: List[str],
    structured: Optional[dict] = None,
    is_error: bool = False,
    resource_link: Optional[dict] = None,
) -> dict:
    content = [_text(t) for t in texts]
    if resource_link:
        content.append(resource_link)
    result: Dict[str, Any] = {"content": content, "isError": is_error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


async def _search_song(args: dict) -> dict:
    query = str(args.get("query") or args.get("song_name") or args.get("keyword") or "").strip()
    limit = int(args.get("limit", 8) or 8)
    limit = max(1, min(limit, 20))
    source_raw = str(args.get("source", "auto") or "auto").strip()
    source = source_raw if source_raw in manager.names else None
    if not query:
        return _tool_result(["请提供搜索关键词 query"], {"songs": []}, is_error=True)
    songs = await manager.search(query, limit=limit, source=source)
    payload = [_song_public(s) for s in songs]
    if not payload:
        return _tool_result(
            [f"没有搜索到与「{query}」相关的歌曲，请换个关键词试试。"],
            {"songs": []},
        )
    text = compact_json(payload)
    summary = f"共找到 {len(payload)} 首与「{query}」相关的歌曲："
    for i, s in enumerate(payload[:6], 1):
        summary += f"\n{i}. {s['title']} - {s['artist']}（{s['source_name']}）"
    return _tool_result([summary, text], {"songs": payload})


async def _resolve_candidates(query: str, song_id: str, source: Optional[str]) -> List[Song]:
    """根据参数构造候选歌曲列表。"""
    if song_id and source:
        src = manager.get(source)
        return [
            Song(
                source=source,
                source_name=src.display_name if src else source,
                song_id=song_id,
                title=query or song_id,
                artist="",
            )
        ]
    songs = await manager.search(query, limit=12, source=source)
    if song_id:
        matched = [s for s in songs if s.song_id == song_id]
        if matched:
            return matched
    return songs


async def _play_song(args: dict) -> dict:
    query = str(args.get("query") or args.get("song_name") or args.get("keyword") or "").strip()
    song_id = str(args.get("song_id", "") or "").strip()
    source_raw = str(args.get("source", "auto") or "auto").strip()
    source = source_raw if source_raw in manager.names else None

    if not query and not song_id:
        return _tool_result(
            ["请提供歌曲名称 query（例如：播放青花瓷），或提供 song_id。"],
            {"playing": False},
            is_error=True,
        )

    try:
        candidates = await _resolve_candidates(query, song_id, source)
    except Exception as exc:
        logger.exception("搜索歌曲失败")
        return _tool_result([f"搜索失败: {exc}"], {"playing": False}, is_error=True)

    if not candidates:
        return _tool_result(
            [f"没有找到「{query or song_id}」对应的歌曲，请换一个说法或歌名。"],
            {"playing": False},
        )

    verify = settings.local_player == "none"  # 本地播放时无需网络验证
    last_error = "未知错误"
    for song in candidates[: settings.max_resolve_tries]:
        try:
            logger.info("[MCP] Resolvendo faixa: '%s' - '%s'", song.title, song.artist)
            play = await manager.resolve(song)
            logger.info("[MCP] Faixa resolvida com sucesso! URL para o Dobi: %s", play.url)
            if not play.url:
                continue
            if verify and not await _verify_url(play.url):
                last_error = f"「{song.title}」的播放地址无法访问（可能已下架或需要会员）"
                continue
            structured = {
                "playing": True,
                "song": _song_public(song),
                "play_url": play.url,
                "mime_type": play.mime_type,
                "source": song.source_name,
            }
            texts = [
                compact_json(
                    {
                        "playing": True,
                        "title": song.title,
                        "artist": song.artist,
                        "source": song.source_name,
                        "message": f"正在播放：{song.title} - {song.artist}",
                    }
                )
            ]
            # Notifica o player web no Render se estiver rodando
            port = os.environ.get("PORT", "8080")
            try:
                import httpx
                async with httpx.AsyncClient(timeout=1.5) as client:
                    await client.post(
                        f"http://127.0.0.1:{port}/api/notify_play",
                        json={
                            "title": song.title,
                            "artist": song.artist,
                            "cover": song.cover_url,
                            "url": play.url,
                        },
                    )
            except Exception:
                pass

            if settings.auto_play_local and player.available:
                msg = player.play(play.url, f"{song.title} - {song.artist}")
                texts.append(msg)
                structured["local_player"] = msg
            return _tool_result(
                texts,
                structured,
                resource_link=_resource_link(song, play.url, play.mime_type),
            )
        except Exception as exc:
            last_error = str(exc)
            logger.warning("解析 %s 播放地址失败: %s", song.title, exc)

    return _tool_result(
        [
            f"无法播放「{query or song_id}」：{last_error}。"
            "已尝试多个音源仍失败，可能是版权限制，请换一首歌试试。"
        ],
        {"playing": False, "reason": last_error},
        is_error=True,
    )


async def _get_play_url(args: dict) -> dict:
    query = str(args.get("query") or args.get("song_name") or args.get("keyword") or "").strip()
    song_id = str(args.get("song_id", "") or "").strip()
    source_raw = str(args.get("source", "auto") or "auto").strip()
    source = source_raw if source_raw in manager.names else None
    if not query and not song_id:
        return _tool_result(["需要 query 或 song_id"], {"play_url": None}, is_error=True)
    candidates = await _resolve_candidates(query, song_id, source)
    if not candidates:
        return _tool_result(["未找到歌曲"], {"play_url": None})
    for song in candidates[: settings.max_resolve_tries]:
        try:
            logger.info("[MCP] Resolvendo faixa: '%s' - '%s'", song.title, song.artist)
            play = await manager.resolve(song)
            logger.info("[MCP] Faixa resolvida com sucesso! URL para o Dobi: %s", play.url)
            if play.url:
                return _tool_result(
                    [compact_json({"title": song.title, "artist": song.artist, "play_url": play.url})],
                    {"song": _song_public(song), "play_url": play.url},
                )
        except Exception as exc:
            logger.debug("get_play_url 失败: %s", exc)
    return _tool_result(["未能解析到播放地址"], {"play_url": None}, is_error=True)


async def _list_sources(args: dict) -> dict:
    health = await manager.health()
    payload = [
        {
            "name": name,
            "display_name": info["name"],
            "ok": info["ok"],
        }
        for name, info in health.items()
    ]
    text = compact_json(payload)
    return _tool_result([f"可用音源 {len(payload)} 个：\n" + text], {"sources": payload})


async def _local_player_control(args: dict) -> dict:
    action = str(args.get("action", "status") or "status").strip()
    if action == "play":
        url = str(args.get("url", "") or "").strip()
        if not url:
            return _tool_result(["需要 url 参数"], {"local_player": player.status()}, is_error=True)
        msg = player.play(url)
        return _tool_result([msg], {"local_player": player.status()})
    if action == "stop":
        port = os.environ.get("PORT", "8080")
        try:
            import httpx
            import asyncio
            async def _n():
                async with httpx.AsyncClient(timeout=1.5) as client:
                    await client.post(f"http://127.0.0.1:{port}/api/notify_stop")
            asyncio.create_task(_n())
        except Exception:
            pass
        msg = player.stop()
        return _tool_result([msg], {"local_player": player.status()})
    if action == "status":
        return _tool_result([compact_json(player.status())], {"local_player": player.status()})
    return _tool_result(
        [f"不支持的 action: {action}（支持 play/stop/status）"],
        {"local_player": player.status()},
        is_error=True,
    )


def build_server() -> MCPServer:
    server = MCPServer(server_name="xiaozhi-music-mcp", version="0.1.0")

    server.add_tool(
        "search_song",
        (
            "在免费音乐源中搜索歌曲。当用户要求找歌、点歌、搜索歌曲或询问某首歌是否存在时使用。"
            "支持按歌名、歌手名或“歌名 歌手”搜索，返回歌曲列表（含音源、歌名、歌手、专辑、时长）。"
        ),
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，例如：青花瓷 或 周杰伦 或 周杰伦 青花瓷"},
                "source": {
                    "type": "string",
                    "enum": SOURCE_CHOICES,
                    "description": "指定音源；auto 表示在所有可用音源中搜索",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "返回结果数量，默认 8"},
            },
            "required": ["query"],
        },
        _search_song,
    )

    server.add_tool(
        "play_song",
        (
            "播放歌曲。用户说“播放xxx”“来一首xxx”“放点xxx”时使用。"
            "传入歌名/歌手后会自动搜索并解析可播放地址；也可传入 search_song 返回的 song_id 和 source 精确播放。"
            "返回内容包含文本信息和 ResourceLink 音频资源（可通过 resource://read_from_http 分页读取后播放）。"
        ),
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "歌曲名，或 歌手 + 歌名，例如：青花瓷"},
                "song_id": {"type": "string", "description": "search_song 返回的歌曲 ID（可选）"},
                "source": {
                    "type": "string",
                    "enum": SOURCE_CHOICES,
                    "description": "指定音源；auto 表示自动选择",
                },
                "prefer_quality": {
                    "type": "string",
                    "enum": ["standard", "high"],
                    "description": "音质偏好，默认 standard",
                },
            },
        },
        _play_song,
    )

    server.add_tool(
        "get_play_url",
        (
            "解析歌曲的直链播放地址。当其他工具需要具体音频 URL 时使用。"
            "参数与 play_song 相同，只返回地址不播放。"
        ),
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "歌曲名或歌手+歌名"},
                "song_id": {"type": "string", "description": "歌曲 ID（可选）"},
                "source": {
                    "type": "string",
                    "enum": SOURCE_CHOICES,
                    "description": "指定音源",
                },
            },
        },
        _get_play_url,
    )

    server.add_tool(
        "list_sources",
        "列出当前可用的免费音乐源及健康状态。",
        {"type": "object", "properties": {}},
        _list_sources,
    )

    server.add_tool(
        "local_player_control",
        (
            "控制本机媒体播放器（mpv/vlc）播放/停止，仅当 LOCAL_PLAYER 配置启用时有效。"
            "用于电脑端本地播放场景；小智硬件播放走 play_song 的音频资源，不需要此工具。"
        ),
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "stop", "status"],
                    "description": "操作类型",
                },
                "url": {"type": "string", "description": "action=play 时必填的音频地址"},
            },
            "required": ["action"],
        },
        _local_player_control,
    )

    async def _read_audio_resource(uri: str, arguments: Optional[dict]) -> list:
        blob = await proxy.read_chunk(arguments)
        return [
            {
                "uri": uri,
                "mimeType": "audio/mpeg",
                "blob": blob,
            }
        ]

    server.add_resource(
        proxy.URI,
        "音频流代理",
        _read_audio_resource,
        mime_type="audio/mpeg",
        description=(
            "通过 HTTP Range 分页读取远程音频。arguments: "
            '{"url": "音频地址", "start": 0, "end": 102400}；'
            "到达末尾返回 base64 编码的 [DONE]。"
        ),
    )
    return server
