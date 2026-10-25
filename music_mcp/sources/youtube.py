"""YouTube 音源适配器（基于 yt-dlp）。"""

from __future__ import annotations

import asyncio
import logging
from typing import List

import yt_dlp

from music_mcp.models import PlayResult, Song
from music_mcp.utils import clean_text
from .base import MusicSource, SourceError

logger = logging.getLogger("music_mcp.sources.youtube")


class YouTubeSource(MusicSource):
    name = "youtube"
    display_name = "YouTube"

    def __init__(self) -> None:
        self._ydl_opts_search = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        self._ydl_opts_resolve = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

    async def search(self, query: str, limit: int = 10) -> List[Song]:
        loop = asyncio.get_running_loop()

        def _search():
            with yt_dlp.YoutubeDL(self._ydl_opts_search) as ydl:
                return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

        try:
            res = await loop.run_in_executor(None, _search)
        except Exception as exc:
            raise SourceError(f"YouTube 搜索失败: {exc}") from exc

        entries = (res or {}).get("entries") or []
        songs: List[Song] = []
        for entry in entries:
            video_id = str(entry.get("id") or "")
            title = clean_text(str(entry.get("title") or ""))
            uploader = clean_text(str(entry.get("uploader") or entry.get("channel") or "YouTube"))
            duration = int(entry.get("duration") or 0)
            if not video_id or not title:
                continue

            thumbnail = ""
            thumbnails = entry.get("thumbnails")
            if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
                thumbnail = thumbnails[-1].get("url", "")

            songs.append(
                Song(
                    source=self.name,
                    source_name=self.display_name,
                    song_id=video_id,
                    title=title,
                    artist=uploader,
                    duration=duration,
                    cover_url=thumbnail,
                    mime_type="audio/mpeg",
                )
            )
        return songs

    async def get_play_url(self, song: Song) -> PlayResult:
        loop = asyncio.get_running_loop()
        video_url = f"https://www.youtube.com/watch?v={song.song_id}"

        def _resolve():
            with yt_dlp.YoutubeDL(self._ydl_opts_resolve) as ydl:
                return ydl.extract_info(video_url, download=False)

        try:
            info = await loop.run_in_executor(None, _resolve)
        except Exception as exc:
            raise SourceError(f"YouTube 解析播放地址失败: {exc}") from exc

        raw_url = str((info or {}).get("url") or "")
        if not raw_url:
            raise SourceError("YouTube 未能提取到播放地址")

        return PlayResult(
            url=raw_url,
            mime_type="audio/mpeg",
            note=f"YouTube: {song.title}",
        )
