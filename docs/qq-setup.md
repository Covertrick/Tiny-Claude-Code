# NapCat 接入

个人 QQ 经 NapCat 暴露 OneBot v11 WebSocket，由 `python -m agent` 连接。

1. 运行 `napcat/` 安装器或 Shell，扫码登录测试号  
2. WebUI 开正向 WS：`ws://127.0.0.1:3001`  
3. **开启「语音转文字」**（或确认 QQ 客户端已开）：让 `record` 事件自带转写 `text`，Bot 侧 0 Token、不跑 Whisper  
4. 配置 `agent/.env`（见 `.env.example`：`API_KEY`、`ONEBOT_WS_URL`、`BOT_QQ`、`QQ_OWNER_QQ`）  
5. 仓库根目录：`python -m agent`

## 建议环境变量

```env
QQ_OWNER_QQ=你的QQ          # 早报 / 关键词 / 健康告警
QQ_ALERT_KEYWORDS=紧急,加急,XX项目
SERVERCHAN_SENDKEY=         # 可选掉线告警
```

## 运维提示

- 进程守护可用 Docker `restart: always` 或 Windows 任务计划；WS 客户端已内置断线重连  
- 健康检查每 60s ping `get_login_info`；断线 ≥5 分钟走 Server 酱 / SMTP / 私聊主人  

详见 [NapCat Releases](https://github.com/NapNeko/NapCatQQ/releases)。
