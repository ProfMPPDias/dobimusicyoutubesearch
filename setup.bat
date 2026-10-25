@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] 检查 uv...
where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未找到 uv，请先安装： https://docs.astral.sh/uv/
    pause
    exit /b 1
)
echo [2/3] 创建虚拟环境（Python 3.13）...
set "UV_CACHE_DIR=%CD%\.uv-cache"
uv venv .venv --python 3.13
if errorlevel 1 (
    echo [ERROR] 创建虚拟环境失败
    pause
    exit /b 1
)
echo [3/3] 安装依赖...
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if not exist .env (
    copy .env.example .env >nul
    echo 已生成 .env，请编辑填写 MCP_ENDPOINT
)
echo 安装完成！运行 run.bat（默认连接小智）或 run.bat server（单独启动 MCP 服务）。
pause
