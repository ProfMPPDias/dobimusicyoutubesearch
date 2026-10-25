"""音源适配器基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from music_mcp.models import PlayResult, Song


class SourceError(Exception):
    """音源请求失败。"""


class MusicSource(ABC):
    """所有音源适配器必须实现 search 与 get_play_url。"""

    name: str = ""
    display_name: str = ""

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> List[Song]:
        raise NotImplementedError

    @abstractmethod
    async def get_play_url(self, song: Song) -> PlayResult:
        raise NotImplementedError
