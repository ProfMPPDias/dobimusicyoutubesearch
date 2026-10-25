"""酷我音源解析测试：模拟接口返回的 Python 字面量格式。"""

from __future__ import annotations

import asyncio

import pytest

from music_mcp.sources.kuwo import KuwoSource, _clean_escapes


BS = chr(92)

# 酷我真实返回：u0026 被转成 4 个反斜杠 + u0026
FAKE_RESPONSE = (
    "{'abslist':[{'MUSICRID':'MUSIC_123',"
    f"'NAME':'{BS*4}u0026青花瓷{BS*4}u0026',"
    f"'ARTIST':'周杰伦{BS*4}u0026那英',"
    "'ALBUM':'我很忙',"
    "'DURATION':'290',"
    "'PICPATH':'https://x/1.jpg'}]}"
)


def test_clean_escapes():
    assert _clean_escapes(f"周杰伦{BS*2}u0026那英") == "周杰伦&那英"
    assert _clean_escapes({"a": [f"x{BS}&y"]}) == {"a": ["x&y"]}


@pytest.mark.asyncio
async def test_search_parses_literal_response(monkeypatch):
    source = KuwoSource()

    async def fake_get(url, params):
        class Resp:
            content = FAKE_RESPONSE.encode("utf-8")

            def raise_for_status(self):
                pass

        return Resp()

    monkeypatch.setattr(source._client, "get", fake_get)
    songs = await source.search("青花瓷", limit=1)
    assert len(songs) == 1
    song = songs[0]
    assert song.song_id == "MUSIC_123"
    assert song.title == "&青花瓷&"
    assert song.artist == "周杰伦&那英"
    assert song.duration == 290
