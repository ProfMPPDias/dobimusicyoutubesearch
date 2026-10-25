# Servidor MCP de Música (YouTube Local Streamer) para o Robô Dobi (XiaoZhi AI)

Este projeto integra o seu robô **Dobi** (que utiliza o ecossistema **XiaoZhi AI / ESP32**) com o **YouTube**, convertendo o áudio em tempo real para **MP3 leve** transmitido diretamente para o robô na sua rede local Wi-Fi.

---

## 📁 Localização do Projeto
`C:\Users\mppdi\.gemini\antigravity\scratch\dobi-youtube-mcp`

---

## ⚙️ Arquitetura da Solução

1. **Adaptador YouTube (`music_mcp/sources/youtube.py`)**:
   - Pesquisa no YouTube via `yt-dlp`.
   - Extrai o áudio em formato de alta qualidade.
2. **Local MP3 Streamer (`music_mcp/http_streamer.py`)**:
   - Converte o fluxo do YouTube em tempo real usando **FFmpeg** para **MP3 padrão (128 kbps)**.
   - Disponibiliza a transmissão em um endpoint HTTP simples na sua rede local (`http://192.168.15.3:8080/stream.mp3`).
   - Evita travamentos de memória (RAM) e erros de SSL no microcontrolador ESP32 do robô.
3. **Ponte WebSocket (`bridge.py`)**:
   - Conectada ao endpoint MCP oficial do seu agente XiaoZhi.

---

## 🚀 Como Iniciar

1. Dê dois cliques em:
   👉 `run.bat`
2. Você verá:
   ```text
   [xiaozhi-music] Successfully connected to WebSocket server
   [STREAMER] Servidor de áudio MP3 para o Robô Dobi ativo em: http://192.168.15.3:8080/stream.mp3
   ```
3. Se o Windows Firewall exibir um alerta perguntando se deseja permitir acesso à rede para o Python, clique em **Permitir acesso**.
4. Fale com o seu robô:
   - *"Dobi, toca a música Bohemian Rhapsody no YouTube"*
   - *"Dobi, toca Evidências"*
