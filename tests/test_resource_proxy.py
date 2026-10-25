"""音频资源代理测试：使用本地 HTTP 服务器，不依赖外网。"""

from __future__ import annotations

import base64
import threading

import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from music_mcp.resource_proxy import STREAM_DONE_FLAG, ResourceProxy


class AudioHandler(BaseHTTPRequestHandler):
    audio = bytes(range(256)) * 8  # 2048 字节音频

    def log_message(self, *args):
        pass

    def do_GET(self):
        range_header = self.headers.get("Range", "")
        if range_header.startswith("bytes="):
            spec = range_header[len("bytes="):]
            start_s, _, end_s = spec.partition("-")
            start = int(start_s)
            end = int(end_s) if end_s else len(self.audio) - 1
            if start >= len(self.audio):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(self.audio)}")
                self.end_headers()
                return
            data = self.audio[start : min(end + 1, len(self.audio))]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{start + len(data) - 1}/{len(self.audio)}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.audio)))
        self.end_headers()
        self.wfile.write(self.audio)


class NoRangeHandler(AudioHandler):
    """忽略 Range 头，总是返回完整文件。"""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.audio)))
        self.end_headers()
        self.wfile.write(self.audio)


@pytest.fixture
def audio_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), AudioHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/a.mp3"
    server.shutdown()


@pytest.fixture
def no_range_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), NoRangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/a.mp3"
    server.shutdown()


@pytest.mark.asyncio
async def test_read_range_chunk(audio_server):
    proxy = ResourceProxy()
    blob = await proxy.read_chunk({"url": audio_server, "start": 0, "end": 1000})
    data = base64.b64decode(blob)
    assert len(data) == 1000
    assert data == bytes(range(256)) * 3 + bytes(range(232))


@pytest.mark.asyncio
async def test_read_eof_returns_done(audio_server):
    proxy = ResourceProxy()
    # 起始位置超出文件长度（2048 字节）时，服务器返回 416 -> [DONE]
    blob = await proxy.read_chunk({"url": audio_server, "start": 2048, "end": 3000})
    assert base64.b64decode(blob) == STREAM_DONE_FLAG.encode()


@pytest.mark.asyncio
async def test_read_short_tail_returns_partial(audio_server):
    proxy = ResourceProxy()
    blob = await proxy.read_chunk({"url": audio_server, "start": 2000, "end": 3000})
    data = base64.b64decode(blob)
    assert len(data) == 48


@pytest.mark.asyncio
async def test_read_no_range_server(audio_server, no_range_server):
    proxy = ResourceProxy()
    # 第一页返回完整文件
    blob = await proxy.read_chunk({"url": no_range_server, "start": 0, "end": 100})
    assert base64.b64decode(blob) == bytes(range(256)) * 8
    # 后续请求返回 [DONE]，避免死循环
    blob2 = await proxy.read_chunk({"url": no_range_server, "start": 100, "end": 200})
    assert base64.b64decode(blob2) == STREAM_DONE_FLAG.encode()


@pytest.mark.asyncio
async def test_invalid_url_rejected():
    proxy = ResourceProxy()
    with pytest.raises(Exception):
        await proxy.read_chunk({"url": "file:///etc/passwd", "start": 0, "end": 10})
