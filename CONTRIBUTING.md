# 贡献指南

欢迎提交 Issue 和 Pull Request！

## 开发环境

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
```

## 本地验证

```bash
# 单元/集成测试（不依赖外网）
.venv/Scripts/python.exe -m pytest tests -q

# 真实音源自检
.venv/Scripts/python.exe scripts/check_sources.py "青花瓷"

# MCP 协议冒烟测试
$env:SMOKE_QUERY="青花瓷"
.venv/Scripts/python.exe scripts/mcp_smoke.py
```

## 新增音源

1. 在 `music_mcp/sources/` 下新建适配器，继承 `MusicSource`
   （实现 `search()` 与 `get_play_url()`，参考 `kuwo.py`）；
2. 在 `music_mcp/sources/__init__.py` 的 `_source_classes()` 中注册；
3. 在 `music_mcp/app.py` 的 `SOURCE_CHOICES` 中补充枚举；
4. 在 README 音源表中补充说明，并为解析逻辑添加测试。

## 代码风格

- 中文注释，函数和参数命名要能让大模型“一看就懂”；
- 工具返回内容保持简短（小智返回长度有限制）；
- 日志一律走 `logging`，禁止向 stdout 输出非协议内容。

## 提交

- 不要提交 `.env`、`logs/`、`.venv/`、`mcp_config.json`；
- 提交前运行 `python -m pytest tests -q` 并保证全部通过。
