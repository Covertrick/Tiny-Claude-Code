# NapCat 接入

个人 QQ 经 NapCat 暴露 OneBot v11 WebSocket，由 `python -m agent` 连接。

## 一键启动（推荐）

仓库根目录：

```bash
python -m agent
# 或
powershell -File scripts/start_qqbot.ps1
```

启动时会自动：

1. 若没有 `agent/.env`，从 `.env.example` 复制  
2. 从 `napcat/Shell/config/webui.json` 读取 WebUI Token / 端口，**写入 `.env`**  
3. 从 `onebot11_*.json` 推断 `BOT_QQ` / `QQ_ACCOUNT`（若 `.env` 为空）  
4. 若本机 `3001` 未监听，自动运行 `napcat/Shell/launcher-user.bat` 拉起 NapCat  
5. 等待 OneBot WS 就绪后再连 Agent  

你只需在 `.env` 里手动保证有 `API_KEY`（DeepSeek）。其余可自动填。

## 手动步骤（可选）

1. 运行 `napcat/` 安装器或 Shell，扫码登录测试号  
2. WebUI 开正向 WS：`ws://127.0.0.1:3001`  
3. **开启「语音转文字」**（或确认 QQ 客户端已开）  
4. 配置 `agent/.env` 的 `API_KEY`  
5. `python -m agent`

## NapCat WebUI Token

浏览器打开 `http://127.0.0.1:6099/webui/web_login` 时要填 Token（不是 QQ 密码）。

### 一键自动登录（推荐）

从 `.env` / `webui.json` 读 Token，按官方算法 `sha256(token+".napcat")` 换票，用 Edge/Chrome 写入 `localStorage` 并打开控制台：

```bash
python -m agent.webui_login
# 或
powershell -File scripts/open_webui.ps1
```

也可在 `.env` 设 `QQ_OPEN_WEBUI=1`，启动 Agent 时顺便自动登录。

### 自动写入 .env

Agent / bootstrap 会把 `napcat/Shell/config/webui.json` 里的 `"token"` 写进：

```env
NAPCAT_WEBUI_HOST=127.0.0.1
NAPCAT_WEBUI_PORT=6099
NAPCAT_WEBUI_TOKEN=……
```

启动日志也会打印当前 Token。

### 手动获取（备用）

1. NapCat 启动日志里的 `WebUi Token` / `登录密钥`  
2. 直接打开 `napcat/Shell/config/webui.json` 看 `"token"`  

> `.env` 已在 `.gitignore`，不要提交真实密钥。

## 建议环境变量

```env
API_KEY=你的DeepSeek密钥
QQ_OWNER_QQ=你的QQ          # 早报 / 关键词 / 健康告警
QQ_ALERT_KEYWORDS=紧急,加急,XX项目
NAPCAT_WEBUI_TOKEN=          # 一般自动填，也可手写
SERVERCHAN_SENDKEY=         # 可选掉线告警
# Reddit 等外网打不开时，指向本机代理（Clash 常见 7890）
# QQ_FETCH_PROXY=http://127.0.0.1:7890
```

贴链接总结：用户发 `https://… 分析这个帖子` 时会自动打开正文（Reddit 走 JSON）。国内直连 Reddit 常超时，需配置 `QQ_FETCH_PROXY`。

## 运维提示

- 进程守护可用 Docker `restart: always` 或 Windows 任务计划；WS 客户端已内置断线重连  
- 健康检查每 60s ping `get_login_info`；断线 ≥5 分钟走 Server 酱 / SMTP / 私聊主人  
- QQ 异地登录 / 被踢时 Agent 会退出全部进程（不再傻重连）

详见 [NapCat Releases](https://github.com/NapNeko/NapCatQQ/releases)。
