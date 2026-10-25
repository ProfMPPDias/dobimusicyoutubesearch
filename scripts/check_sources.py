"""音源自检脚本：测试各音源搜索与播放地址解析。

用法:
    python scripts/check_sources.py "青花瓷" [--source kuwo] [--no-resolve]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from music_mcp.sources import manager  # noqa: E402
from music_mcp.utils import setup_logging  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="音源自检")
    parser.add_argument("query", nargs="?", default=os.environ.get("SMOKE_QUERY", "青花瓷"), help="搜索关键词")
    parser.add_argument("--source", default=None, help="指定音源")
    parser.add_argument("--no-resolve", action="store_true", help="只测试搜索，不解析播放地址")
    args = parser.parse_args()

    print(f"可用音源: {manager.names}")
    songs = await manager.search(args.query, limit=8, source=args.source)
    print(f"\n搜索「{args.query}」共 {len(songs)} 条:")
    for i, s in enumerate(songs, 1):
        print(f"  {i}. [{s.source_name}] {s.title} - {s.artist} | id={s.song_id} | {s.duration}s")

    if args.no_resolve or not songs:
        return 0

    print("\n解析播放地址:")
    seen = set()
    for s in songs:
        key = s.source + "|" + s.song_id
        if key in seen:
            continue
        seen.add(key)
        try:
            play = await manager.resolve(s)
            print(f"  [{s.source_name}] {s.title} -> {play.url} ({play.mime_type})")
        except Exception as exc:
            print(f"  [{s.source_name}] {s.title} -> 失败: {exc}")
    return 0


if __name__ == "__main__":
    setup_logging("WARNING")
    sys.exit(asyncio.run(main()))
