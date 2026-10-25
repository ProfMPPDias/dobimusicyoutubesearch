"""Controle de reprodução de áudio local (ffplay / mpv / vlc)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Dict, Optional

from music_mcp.config import settings

logger = logging.getLogger("music_mcp.local_player")


class LocalPlayer:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._current: str = ""

    @property
    def available(self) -> bool:
        return settings.local_player in ("mpv", "vlc", "ffplay")

    @property
    def player_path(self) -> Optional[str]:
        if settings.local_player == "mpv":
            name = "mpv.exe"
        elif settings.local_player == "vlc":
            name = "vlc.exe"
        elif settings.local_player == "ffplay":
            name = "ffplay.exe"
        else:
            name = ""
        return shutil.which(name) if name else None

    def play(self, url: str, title: str = "") -> str:
        if not self.available:
            return "本地播放器未启用（LOCAL_PLAYER 配置为 none）"
        exe = self.player_path
        if not exe:
            return f"未找到 {settings.local_player} 可执行文件，请安装并加入 PATH"
        self.stop()
        if settings.local_player == "mpv":
            cmd = [exe, "--no-video", "--really-quiet", "--force-window=no", url]
        elif settings.local_player == "vlc":
            cmd = [exe, "--intf", "dummy", url]
        elif settings.local_player == "ffplay":
            cmd = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", url]
        else:
            cmd = [exe, url]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._current = url
            logger.info("🎵 [AUDIO LOCAL] Tocando no PC: %s (%s)", title or url, settings.local_player)
            return f"Tocando agora no PC: {title or url}"
        except Exception as exc:
            logger.warning("Falha ao tocar no player local: %s", exc)
            return f"Falha na reprodução local: {exc}"

    def stop(self) -> str:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._current = ""
        return "Reprodução pausada/parada"

    def status(self) -> dict:
        running = bool(self._proc and self._proc.poll() is None)
        return {
            "player": settings.local_player,
            "available": self.available,
            "running": running,
            "current_url": self._current,
        }


player = LocalPlayer()
