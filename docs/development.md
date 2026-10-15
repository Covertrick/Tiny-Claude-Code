# 开发说明

## 目录与边界

见 [architecture.md](./architecture.md)。根 README 有功能全表。

| 目录 | 职责 | 禁止 |
|------|------|------|
| `channel/` | 听/说 QQ、缓存、拦截、拼 Prompt、信号量 | 直接调 DeepSeek HTTP |
| `core/` | 统一 Agent Loop | 感知 QQ 协议细节 |
| `tools/qq.py` | QQ 工具白名单 | bash / edit / Task DAG / MCP |
| `knowledge/` | 多租户记忆目录 | 跨用户读写 |
| `schedules/` + `scheduler.py` | 任务 list + 本地催办 | 催办走 LLM |
| `bootstrap_napcat.py` | 补 `.env`、启 NapCat | 替代用户填 API_KEY |

## 运行

```bash
pip install -r requirements.txt
# agent/.env 至少 API_KEY
python -m agent.smoke_test
python -m agent.demo
python -m agent                 # 自动引导 NapCat
powershell -File scripts/start_qqbot.ps1
```

## 路线图（别一次吃完）

1. ~~三层绞杀 + QQ 去写码工具~~  
2. ~~多租户记忆 · 催办 · 文件摘要 · 主动提醒~~  
3. ~~跨私聊文件 · 删除确认 · 异地登录退出 · 启动引导~~  
4. ~~令牌桶+抖动熔断 · 凭证热更新 · 滚动摘要 · SHA256 去重 · ZoneInfo · 注入隔离~~  
5. **后置（重依赖）**：  
   - 全文 PDF/DOCX 切片 RAG（pypdf 等）  
   - FastEmbed / onnx + sqlite-vec 语义向量  
   - 图片 OCR / 多模态视觉  
   - 全面 asyncio + Redis  

## 简历表述（诚实）

**项目**：基于自研 Agent Loop 的 QQ 智能助手（OneBot / NapCat）

- 事件驱动 OneBot；频道与 Coding CLI 共用 loop，工具面隔离  
- 用户/群目录隔离记忆 + APScheduler 多点催办（0 Token）  
- 群未 @ 只缓存；@ 时滑动窗口按需进模型；文件按上下文一句话摘要  
- 并发信号量控压；异地登录退出；启动自动补配置并拉起 NapCat  

避免写：未实现的 Multi-Agent / LangGraph / Redis / Chroma / 7×24（除非已上服务器守护）。
