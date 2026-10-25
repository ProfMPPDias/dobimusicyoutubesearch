"""咪咕音乐音源（实验性）。

搜索走咪咕 App 公开接口（pd.musicapp.migu.cn），可正常返回结果；
完整播放地址需要 App 签名，通常只能拿到试听片段，因此标记为实验性。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from music_mcp.config import settings
from music_mcp.models import PlayResult, Song
from music_mcp.utils import clean_text

from .base import MusicSource, SourceError

logger = logging.getLogger("music_mcp.sources.migu")


class MiguSource(MusicSource):
    name = "migu"
    display_name = "咪咕音乐"

    SEARCH_URL = "https://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/search_all.do"
    PLAY_URL = "https://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/sub/listen.do"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=settings.source_timeout,
            follow_redirects=True,
            proxy=settings.http_proxy,
            headers={
                "User-Agent": settings.user_agent,
                "Referer": "https://app.migu.cn/",
                "channel": "1000007",
                "Accept": "application/json, text/plain, */*",
            },
        )

    async def search(self, query: str, limit: int = 10) -> List[Song]:
        params = {
            "ua": "Android_migu",
            "version": "5.1",
            "text": query,
            "pageNo": "1",
            "pageSize": str(limit),
            "searchSwitch": '{"song":1,"album":0,"singer":0,"tagSong":0,"mvSong":0,"songlist":0,"bestShow":1}',
        }
        try:
            resp = await self._client.get(self.SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SourceError(f"咪咕搜索失败: {exc}") from exc

        items = (((data or {}).get("songResultData") or {}).get("result")) or []
        songs: List[Song] = []
        for item in items:
            cid = str(item.get("copyrightId", "") or "")
            title = str(item.get("name", "") or "").strip()
            title = clean_text(title)
            if not cid or not title:
                continue
            singer = item.get("singers") or []
            if isinstance(singer, list):
                singer = " / ".join(clean_text(s.get("name", "") or "") for s in singer if isinstance(s, dict))
            singer = str(singer or "未知歌手")
            imgs = item.get("imgItems") or []
            cover = ""
            if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
                cover = clean_text(imgs[0].get("img", "") or "")
            album = item.get("albums") or []
            if isinstance(album, list) and album and isinstance(album[0], dict):
                album = clean_text(album[0].get("name", "") or "")
            else:
                album = ""
            songs.append(
                Song(
                    source=self.name,
                    source_name=self.display_name,
                    song_id=cid,
                    title=title,
                    artist=singer,
                    album=album,
                    cover_url=cover,
                    extra={"content_id": clean_text(item.get("contentId", "") or "")},
                )
            )
        return songs

    async def get_play_url(self, song: Song) -> PlayResult:
        content_id = song.extra.get("content_id", "")
        params = {
            "copyrightId": song.song_id,
            "contentId": content_id,
            "resourceType": "2",
            "rateType": "PQ",
            "channel": "1000007",
            "netType": "01",
            "ua": "Android_migu",
            "version": "5.1",
            "toneFlag": "PQ",
        }
        try:
            resp = await self._client.get(self.PLAY_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SourceError(f"咪咕解析播放地址失败: {exc}") from exc

        # 完整播放需要签名；data.playUrl 偶尔可直接使用
        url = str((data or {}).get("playUrl", "") or "").strip()
        if url:
            return PlayResult(url=url, mime_type="audio/mpeg", note="咪咕音乐")
        raise SourceError("咪咕完整播放需要会员/签名（实验性音源）")
