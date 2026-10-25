"""酷我音乐音源。

来自开源社区常用方案（参考 LX Music / MusicFree 酷我音源）：
搜索: search.kuwo.cn/r.s
播放: antiserver.kuwo.cn/anti.s  -> 返回可直接播放的 mp3 地址
"""

from __future__ import annotations

import logging
import ast
import json
from typing import Any, Dict, List

import httpx

from music_mcp.config import settings
from music_mcp.models import PlayResult, Song
from music_mcp.utils import clean_text

from .base import MusicSource, SourceError

logger = logging.getLogger("music_mcp.sources.kuwo")


def _clean_escapes(obj: Any) -> Any:
    """清理酷我返回文本中的多重转义（反斜杠 u0026、反斜杠 & 等）。"""
    if isinstance(obj, dict):
        return {k: _clean_escapes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_escapes(v) for v in obj]
    if isinstance(obj, str):
        text = obj.replace("\\u0026", "&")
        text = text.replace("\\&", "&")
        text = text.replace("&nbsp;", " ")
        return text
    return obj


class KuwoSource(MusicSource):
    name = "kuwo"
    display_name = "酷我音乐"

    SEARCH_URL = "https://search.kuwo.cn/r.s"
    PLAY_URL = "https://antiserver.kuwo.cn/anti.s"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=settings.source_timeout,
            follow_redirects=True,
            proxy=settings.http_proxy,
            headers={
                "User-Agent": settings.user_agent,
                "Referer": "https://www.kuwo.cn/",
            },
        )

    async def search(self, query: str, limit: int = 10) -> List[Song]:
        params = {
            "all": query,
            "ft": "music",
            "itemset": "web_2013",
            "client": "kt",
            "pn": "0",
            "rn": str(limit),
            "rformat": "json",
            "encoding": "utf8",
        }
        try:
            resp = await self._client.get(self.SEARCH_URL, params=params)
            resp.raise_for_status()
            # 酷我接口返回的是 Python 字面量（单引号 dict），不是标准 JSON。
            # 内容为 UTF-8，但其中 & 被转义成了多重反斜杠的 \\u0026。
            raw_text = resp.content.decode("utf-8", errors="replace")
            data = ast.literal_eval(raw_text)
        except Exception as exc:
            raise SourceError(f"酷我搜索失败: {exc}") from exc

        data = _clean_escapes(data)
        items = (data or {}).get("abslist") or []
        songs: List[Song] = []
        for item in items:
            rid = str(item.get("MUSICRID", "") or item.get("musicrid", ""))
            title = str(
                item.get("NAME", "")
                or item.get("SONGTITLE", "")
                or item.get("SONGNAME", "")
                or ""
            ).strip()
            title = clean_text(title)
            if not rid or not title:
                continue
            try:
                duration = int(item.get("DURATION", 0) or 0)
            except (TypeError, ValueError):
                duration = 0
            songs.append(
                Song(
                    source=self.name,
                    source_name=self.display_name,
                    song_id=rid,
                    title=title,
                    artist=clean_text(item.get("ARTIST", "") or item.get("artist", "") or "未知歌手"),
                    album=clean_text(item.get("ALBUM", "") or item.get("album", "") or ""),
                    duration=duration,
                    cover_url=clean_text(
                        item.get("PICPATH", "")
                        or item.get("web_albumpic_short", "")
                        or item.get("WEB_ALBUM_PIC", "")
                        or ""
                    ),
                )
            )
        return songs

    async def get_play_url(self, song: Song) -> PlayResult:
        rid = song.song_id
        params = {
            "type": "convert_url3",
            "rid": rid,
            "format": "mp3",
            "response": "url",
        }
        try:
            resp = await self._client.get(self.PLAY_URL, params=params)
            resp.raise_for_status()
            text = resp.text.strip()
            url = ""
            if text.startswith("{"):
                try:
                    url = str(json.loads(text).get("url", "") or "").strip()
                except Exception:
                    url = ""
            else:
                url = text
            if not url or url.lower() in ("null", "none", "error"):
                # 部分歌曲只有 aac，尝试 aac 格式
                params["format"] = "aac"
                resp = await self._client.get(self.PLAY_URL, params=params)
                resp.raise_for_status()
                text = resp.text.strip()
                if text.startswith("{"):
                    try:
                        url = str(json.loads(text).get("url", "") or "").strip()
                    except Exception:
                        url = ""
                else:
                    url = text
            if not url:
                raise SourceError("酷我未返回播放地址（可能为付费歌曲）")
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(f"酷我解析播放地址失败: {exc}") from exc
        return PlayResult(url=url, mime_type="audio/mpeg", note="酷我音乐")
