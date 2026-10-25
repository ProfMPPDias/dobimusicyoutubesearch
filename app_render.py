"""Servidor Web & MCP para Deploy no Render (24/7 na Nuvem).

Funcionalidades:
1. Conecta ao endpoint MCP da XiaoZhi 24 horas por dia.
2. Fornece o Web Player para PC, Celular, Smart TV ou Caixa Bluetooth (porta $PORT ou 8080).
3. Transmite eventos de reprodução do YouTube em tempo real via WebSocket para qualquer navegador conectado.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Set

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

# Configura logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("dobi_render")

# Clientes web conectados (navegadores no PC, celular, etc.)
_connected_browsers: Set[web.WebSocketResponse] = set()

# Estado atual da música
_current_state = {
    "is_playing": False,
    "title": "Nenhuma música tocando",
    "artist": "Aguardando comando do Robô Dobi...",
    "url": "",
    "cover": "",
}


async def broadcast_to_browsers(data: dict) -> None:
    """Envia comandos de áudio (play, stop) para todos os navegadores abertos."""
    for ws in list(_connected_browsers):
        try:
            await ws.send_json(data)
        except Exception:
            _connected_browsers.discard(ws)


HTML_PLAYER = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dobi Music Player - Som do Robô</title>
    <link rel="icon" href="https://img.icons8.com/color/96/robot-2.png">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f111a;
            color: #ffffff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .card {
            background: #1a1d2e;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 24px;
            padding: 32px;
            width: 100%;
            max-width: 480px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 700;
            font-size: 1.1rem;
            color: #ffca28;
        }
        .badge {
            background: rgba(38, 166, 154, 0.2);
            color: #26a69a;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .badge.off {
            background: rgba(239, 83, 80, 0.2);
            color: #ef5350;
        }
        .badge-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: currentColor;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { opacity: 0.5; transform: scale(0.9); }
            50% { opacity: 1; transform: scale(1.2); }
            100% { opacity: 0.5; transform: scale(0.9); }
        }
        .cover-box {
            width: 200px;
            height: 200px;
            margin: 0 auto 24px;
            border-radius: 20px;
            background: #252a40;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            border: 2px solid rgba(255, 202, 40, 0.2);
        }
        .cover-box img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .song-title {
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 6px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .song-artist {
            font-size: 0.95rem;
            color: #9e9ea7;
            margin-bottom: 24px;
        }
        .unlock-btn {
            background: #ffca28;
            color: #000;
            font-weight: 700;
            border: none;
            padding: 14px 24px;
            border-radius: 14px;
            cursor: pointer;
            width: 100%;
            font-size: 1rem;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.2s;
        }
        .unlock-btn:hover {
            background: #ffd54f;
            transform: translateY(-2px);
        }
        .unlock-btn.active {
            background: rgba(255, 255, 255, 0.08);
            color: #26a69a;
            cursor: default;
            transform: none;
        }
        audio {
            width: 100%;
            margin-top: 10px;
            border-radius: 10px;
        }
        .footer {
            margin-top: 24px;
            font-size: 0.8rem;
            color: #6c7086;
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <div class="brand">
                <span>🤖</span> Dobi Cloud Player
            </div>
            <div id="statusBadge" class="badge">
                <span class="badge-dot"></span>
                <span id="statusText">Conectando...</span>
            </div>
        </div>

        <div class="cover-box">
            <img id="coverImg" src="https://img.icons8.com/color/192/youtube-music.png" alt="Capa">
        </div>

        <div id="songTitle" class="song-title">Nenhuma música tocando</div>
        <div id="songArtist" class="song-artist">Peça ao Dobi: "Dobi, toca [música]"</div>

        <button id="unlockBtn" class="unlock-btn" onclick="enableAudio()">
            🔊 Clique para Ativar Áudio da Caixa
        </button>

        <audio id="audioPlayer" controls></audio>

        <div class="footer">
            Mantenha esta página aberta no seu PC, celular ou tablet conectado à sua caixa de som Bluetooth. Quando você falar com o Dobi, a música tocará aqui automaticamente!
        </div>
    </div>

    <script>
        const audio = document.getElementById('audioPlayer');
        const unlockBtn = document.getElementById('unlockBtn');
        const statusBadge = document.getElementById('statusBadge');
        const statusText = document.getElementById('statusText');
        const songTitle = document.getElementById('songTitle');
        const songArtist = document.getElementById('songArtist');
        const coverImg = document.getElementById('coverImg');

        let audioEnabled = false;

        function enableAudio() {
            audio.play().then(() => {
                audio.pause();
                audioEnabled = true;
                unlockBtn.innerHTML = "✅ Áudio Ativo na Caixa de Som";
                unlockBtn.classList.add("active");
            }).catch(() => {
                audioEnabled = true;
                unlockBtn.innerHTML = "✅ Áudio Ativo na Caixa de Som";
                unlockBtn.classList.add("active");
            });
        }

        function connectWS() {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${proto}//${window.location.host}/ws`);

            ws.onopen = () => {
                statusBadge.classList.remove('off');
                statusText.innerText = "Conectado ao Dobi";
            };

            ws.onclose = () => {
                statusBadge.classList.add('off');
                statusText.innerText = "Desconectado (Reconectando...)";
                setTimeout(connectWS, 2000);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.action === 'play') {
                        songTitle.innerText = data.title || "Tocando Música";
                        songArtist.innerText = data.artist || "YouTube";
                        if (data.cover) coverImg.src = data.cover;
                        audio.src = data.url;
                        audio.play().catch(e => console.log("Aguardando clique para reproduzir:", e));
                    } else if (data.action === 'stop') {
                        audio.pause();
                        songTitle.innerText = "Música pausada";
                        songArtist.innerText = "Aguardando novo comando...";
                    }
                } catch (e) {
                    console.error("Erro ao processar mensagem:", e);
                }
            };
        }

        connectWS();
    </script>
</body>
</html>
"""


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=HTML_PLAYER, content_type="text/html")


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _connected_browsers.add(ws)
    logger.info("Novo navegador/dispositivo conectado ao Player Web! Total: %d", len(_connected_browsers))

    # Envia o estado atual
    if _current_state["is_playing"] and _current_state["url"]:
        await ws.send_json({
            "action": "play",
            "title": _current_state["title"],
            "artist": _current_state["artist"],
            "cover": _current_state["cover"],
            "url": _current_state["url"],
        })

    try:
        async for msg in ws:
            pass
    finally:
        _connected_browsers.discard(ws)
        logger.info("Navegador desconectado. Total restante: %d", len(_connected_browsers))

    return ws


# ---------------------------------------------------------------------------
# MCP Bridge Integrado (Conversa com o XiaoZhi da Cloud)
# ---------------------------------------------------------------------------

async def handle_mcp_play(song_info: dict) -> None:
    """Acionado quando o Dobi pede uma música pelo MCP."""
    _current_state["is_playing"] = True
    _current_state["title"] = song_info.get("title", "Desconhecido")
    _current_state["artist"] = song_info.get("artist", "YouTube")
    _current_state["cover"] = song_info.get("cover", "")
    _current_state["url"] = song_info.get("url", "")

    logger.info("🎵 [MCP CLOUD] Transmitindo para os navegadores: '%s' - '%s'", _current_state["title"], _current_state["artist"])
    await broadcast_to_browsers({
        "action": "play",
        "title": _current_state["title"],
        "artist": _current_state["artist"],
        "cover": _current_state["cover"],
        "url": _current_state["url"],
    })


async def handle_mcp_stop() -> None:
    """Acionado quando o Dobi pede para parar/pausar."""
    _current_state["is_playing"] = False
    logger.info("⏹️ [MCP CLOUD] Pausando reprodução nos navegadores.")
    await broadcast_to_browsers({"action": "stop"})


def ensure_mcp_config() -> None:
    """Garante que mcp_config.json exista e utilize o executável Python atual (Linux ou Windows)."""
    config_path = Path("mcp_config.json")
    sources = os.environ.get("MUSIC_SOURCES", "youtube")
    config = {
        "mcpServers": {
            "xiaozhi-music": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "music_mcp"],
                "env": {
                    "MUSIC_SOURCES": sources,
                    "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO"),
                },
            }
        }
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logger.info("Configuração mcp_config.json garantida com Python: %s", sys.executable)


async def run_mcp_bridge_task(endpoint: str) -> None:
    """Tarefa em background que mantém a conexão WebSocket com a XiaoZhi."""
    ensure_mcp_config()
    import mcp_pipe
    while True:
        try:
            logger.info("Conectando ao endpoint MCP da XiaoZhi: %s...", endpoint[:40])
            await mcp_pipe.run_pipe(endpoint, None)
        except Exception as exc:
            logger.warning("Conexão MCP caiu: %s. Reconectando em 5 segundos...", exc)
            await asyncio.sleep(5)


async def handle_notify_play(request: web.Request) -> web.Response:
    data = await request.json()
    await handle_mcp_play(data)
    return web.json_response({"status": "ok"})


async def handle_notify_stop(request: web.Request) -> web.Response:
    await handle_mcp_stop()
    return web.json_response({"status": "ok"})


def setup_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", handle_ws)
    app.router.add_post("/api/notify_play", handle_notify_play)
    app.router.add_post("/api/notify_stop", handle_notify_stop)
    return app


async def main() -> None:
    port = int(os.environ.get("PORT", 8080))
    endpoint = os.environ.get("MCP_ENDPOINT")

    if not endpoint:
        logger.error("ERRO: Variável MCP_ENDPOINT não configurada no Render/Ambiente!")

    app = setup_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("🚀 Servidor Web Player ativo na porta %d!", port)

    # Inicia a ponte MCP em segundo plano
    if endpoint:
        asyncio.create_task(run_mcp_bridge_task(endpoint))

    # Mantém rodando para sempre
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
