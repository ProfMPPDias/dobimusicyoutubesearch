"""酷狗音乐音源（实验性）。

搜索接口正常；播放接口对部分版权歌曲返回空地址，作为兜底音源。
"""

from __future__ import annotations

import logging
from typing import List

import httpx

from music_mcp.config import settings
from music_mcp.models import PlayResult, Song
from music_mcp.utils import clean_text

from .base import MusicSource, SourceError

logger = logging.getLogger("music_mcp.sources.kugou")


class KugouSource(MusicSource):
    name = "kugou"
    display_name = "酷狗音乐"

    SEARCH_URL = "https://songsearch.kugou.com/song_search_v2"
    PLAY_URL = "https://m.kugou.com/app/i/getSongInfo.php"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=settings.source_timeout,
            follow_redirects=True,
            proxy=settings.http_proxy,
            headers={
                "User-Agent": settings.user_agent,
                "Referer": "https://www.kugou.com/",
            },
        )

    async def search(self, query: str, limit: int = 10) -> List[Song]:
        params = {
            "keyword": query,
            "page": "1",
            "pagesize": str(limit),
            "userid": "-1",
            "clientver": "2000",
            "platform": "WebFilter",
            "tag": "em",
            "filter": "2",
            "iscorrection": "1",
            "privilege_filter": "0",
        }
        try:
            resp = await self._client.get(self.SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SourceError(f"酷狗搜索失败: {exc}") from exc

        items = (((data or {}).get("data") or {}).get("lists")) or []
        songs: List[Song] = []
        for item in items:
            fhash = str(item.get("FileHash", "") or "")
            title = str(item.get("SongName", "") or "").strip()
            title = clean_text(title.replace("<em>", "").replace("</em>", ""))
            if not fhash or not title:
                continue
            try:
                duration = int(item.get("Duration", 0) or 0)
            except (TypeError, ValueError):
                duration = 0
            songs.append(
                Song(
                    source=self.name,
                    source_name=self.display_name,
                    song_id=fhash,
                    title=title,
                    artist=clean_text(item.get("SingerName", "") or "未知歌手"),
                    album=clean_text(item.get("AlbumName", "") or ""),
                    duration=duration,
                    cover_url=clean_text(item.get("ImgUrl", "") or ""),
                )
            )
        return songs

    async def get_play_url(self, song: Song) -> PlayResult:
        params = {
            "cmd": "playInfo",
            "hash": song.song_id,
        }
        try:
            resp = await self._client.get(self.PLAY_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SourceError(f"酷狗解析播放地址失败: {exc}") from exc

        url = str((data or {}).get("url", "") or "").strip()
        if not url:
            raise SourceError("酷狗该歌曲不可用（可能为付费歌曲）")
        return PlayResult(url=url, mime_type="audio/mpeg", note="酷狗音乐")
