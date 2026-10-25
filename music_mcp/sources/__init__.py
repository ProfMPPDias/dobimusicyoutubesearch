"""音乐源管理器：注册、搜索、解析播放地址。"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from music_mcp.config import settings
from music_mcp.models import PlayResult, Song

from .base import SourceError, MusicSource
from .kuwo import KuwoSource
from .netease import NeteaseSource
from .migu import MiguSource
from .kugou import KugouSource
from .youtube import YouTubeSource

logger = logging.getLogger("music_mcp.sources")


def _source_classes() -> Dict[str, type]:
    return {
        "youtube": YouTubeSource,
        "kuwo": KuwoSource,
        "netease": NeteaseSource,
        "migu": MiguSource,
        "kugou": KugouSource,
    }


class SourceManager:
    def __init__(self, enabled: Optional[List[str]] = None):
        enabled = enabled or settings.enabled_sources
        classes = _source_classes()
        self.sources: Dict[str, MusicSource] = {}
        for name in enabled:
            cls = classes.get(name)
            if cls is None:
                logger.warning("未知音源 %s，已跳过", name)
                continue
            try:
                self.sources[name] = cls()
            except Exception as exc:  # pragma: no cover
                logger.warning("初始化音源 %s 失败: %s", name, exc)
        if not self.sources:
            logger.warning("没有可用的音源，请检查 MUSIC_SOURCES 配置")

    @property
    def names(self) -> List[str]:
        return list(self.sources.keys())

    def get(self, name: str) -> Optional[MusicSource]:
        return self.sources.get(name)

    async def search(
        self,
        query: str,
        limit: int = 8,
        source: Optional[str] = None,
    ) -> List[Song]:
        """在指定或全部音源中搜索，结果按 音源->相关度 顺序返回。"""
        if not query.strip():
            return []
        names = [source] if source and source in self.sources else self.names
        per_source = max(1, (limit + len(names) - 1) // len(names))
        results: List[Song] = []
        for name in names:
            try:
                songs = await self.sources[name].search(query, limit=per_source)
                results.extend(songs)
            except Exception as exc:
                logger.warning("音源 %s 搜索失败: %s", name, exc)
        return results[:limit]

    async def resolve(self, song: Song) -> PlayResult:
        src = self.sources.get(song.source)
        if src is None:
            raise SourceError(f"音源 {song.source} 不可用")
        return await src.get_play_url(song)

    async def health(self, max_age_seconds: int = 300) -> Dict[str, dict]:
        """返回各音源健康状态（带 5 分钟缓存）。"""
        now = time.time()
        if not hasattr(self, "_health_cache"):
            self._health_cache: Dict[str, tuple] = {}
        out: Dict[str, dict] = {}
        for name, src in self.sources.items():
            cached = self._health_cache.get(name)
            if cached and now - cached[0] < max_age_seconds:
                out[name] = cached[1]
                continue
            try:
                songs = await src.search("queen", limit=1)
                ok = bool(songs)
            except Exception:
                ok = False
            info = {
                "ok": ok,
                "name": src.display_name,
            }
            self._health_cache[name] = (now, info)
            out[name] = info
        return out


manager = SourceManager()
