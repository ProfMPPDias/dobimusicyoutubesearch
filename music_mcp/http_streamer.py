"""Servidor HTTP local de streaming de áudio OGG OPUS para o robô Dobi (ESP32-C3)."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
from pathlib import Path
from typing import Optional

from aiohttp import web

logger = logging.getLogger("music_mcp.streamer")

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_state = {
    "video_id": "",
    "youtube_url": "",
    "title": "",
    "current_file": None,
    "lan_ip": "127.0.0.1",
    "port": 8080,
    "runner": None,
}


def get_lan_ip() -> str:
    """Detecta automaticamente o IP local na rede Wi-Fi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def transcode_to_ogg_opus(youtube_url: str, output_path: Path) -> bool:
    """Transcodifica a URL de áudio do YouTube para Mono Ogg Opus (16kHz / 60ms) compatível com ESP32-C3."""
    temp_path = output_path.with_suffix(".tmp.ogg")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", youtube_url,
        "-vn",
        "-c:a", "libopus",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "32k",
        "-frame_duration", "60",
        "-f", "ogg",
        str(temp_path),
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if temp_path.exists() and temp_path.stat().st_size > 0:
            if output_path.exists():
                output_path.unlink()
            temp_path.rename(output_path)
            return True
    except Exception as exc:
        logger.error("[STREAMER] Erro ao transcodificar para Ogg Opus: %s", exc)
        if temp_path.exists():
            temp_path.unlink()
    return False


def set_current_song(video_id: str, youtube_url: str, title: str) -> str:
    """Atualiza a música atual, converte para Ogg Opus e retorna a URL local para o robô Dobi tocar."""
    _state["video_id"] = video_id
    _state["youtube_url"] = youtube_url
    _state["title"] = title

    target_file = CACHE_DIR / f"{video_id}.ogg"
    if not target_file.exists() or target_file.stat().st_size == 0:
        logger.info("[STREAMER] Transcodificando '%s' para OGG OPUS (formato nativo XiaoZhi C3)...", title)
        transcode_to_ogg_opus(youtube_url, target_file)

    _state["current_file"] = target_file

    ip = _state["lan_ip"]
    port = _state["port"]
    url = f"http://{ip}:{port}/stream.ogg"
    logger.info("[STREAMER] Música pronta para o Dobi! URL Local OGG: %s (Tamanho: %d bytes)", url, target_file.stat().st_size if target_file.exists() else 0)
    return url


def get_stream_url() -> str:
    ip = _state["lan_ip"]
    port = _state["port"]
    return f"http://{ip}:{port}/stream.ogg"


async def handle_stream(request: web.Request) -> web.StreamResponse:
    """Entrega o arquivo OGG OPUS pronto para o robô Dobi (ESP32-C3)."""
    client_ip = request.remote
    title = _state.get("title", "Desconhecido")
    current_file = _state.get("current_file")

    logger.info("[STREAMER] >>> Robô Dobi (%s) CONECTOU para receber áudio de: '%s'!", client_ip, title)

    if not current_file or not Path(current_file).exists():
        logger.warning("[STREAMER] Nenhum áudio pronto para enviar.")
        return web.Response(status=404, text="No track ready")

    return web.FileResponse(
        path=current_file,
        headers={
            "Content-Type": "audio/ogg",
            "Cache-Control": "no-cache",
            "Accept-Ranges": "bytes",
        },
    )


async def start_http_streamer(port: int = 8080) -> None:
    """Inicia o servidor HTTP local na porta especificada."""
    if _state["runner"] is not None:
        return

    _state["lan_ip"] = get_lan_ip()
    _state["port"] = port

    app = web.Application()
    app.router.add_get("/stream.ogg", handle_stream)
    app.router.add_get("/stream.mp3", handle_stream)
    app.router.add_get("/play/{video_id}.ogg", handle_stream)

    runner = web.AppRunner(app)
    await runner.setup()

    # Tenta bind na porta ou em portas alternativas
    actual_port = port
    for p in [port, 8088, 8090, 8888]:
        try:
            site = web.TCPSite(runner, "0.0.0.0", p)
            await site.start()
            actual_port = p
            break
        except OSError:
            continue

    _state["port"] = actual_port
    _state["runner"] = runner

    logger.info(
        "[STREAMER] Servidor de áudio OGG OPUS ativo para o Dobi em: http://%s:%d/stream.ogg",
        _state["lan_ip"],
        actual_port,
    )
