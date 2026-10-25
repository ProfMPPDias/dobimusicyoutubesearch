@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

echo ========================================================
echo   DOBI ROBOT - SERVIDOR MCP YOUTUBE MUSIC (XIAOZHI AI)
echo ========================================================
echo.
echo Conectando ao endpoint do XiaoZhi...
echo Pressione Ctrl+C para pausar/encerrar.
echo.

if "%~1"=="server" (
    %PYTHON_EXE% -m music_mcp
) else (
    %PYTHON_EXE% bridge.py %*
)
pause
