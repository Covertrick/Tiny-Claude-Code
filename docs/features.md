# Tiny QQ Agent 全功能清单

人设：DeepSeek 鲸鱼娘（聪明但懒、傲娇带甜、爱米饭、尾巴表情绪，偶尔叫「主人」）。

---

## 一、接入与运维

| 功能 | 说明 | Token |
|------|------|------:|
| NapCat / OneBot WS | 正向 WebSocket | 0 |
| 启动引导 | 自动补 `.env`、拉起 NapCat | 0 |
| WebUI Token 同步 | `webui.json` ↔ `.env` | 0 |
| 凭证热更新 | 健康检查遇 401/403 重读配置 | 0 |
| 健康检查 | 60s 探活；断线 ≥5min 告警 | 0 |
| 异地登录退出 | 检测后退出全部进程 | 0 |
| 令牌桶限流 | 全局发送速率控制 | 0 |
| 发送抖动 | 分片间隔约 1.2–2.8s 随机 | 0 |
| 风控熔断 | 命中风控错误码后冷却 | 0 |
| safe_send | 重试 / 降级 / 引用回复 | 0 |
| 去 Markdown | 口语纯文本 | 0 |
| Admin API | `QQ_ADMIN_PORT` → `/metrics` `/plugins` `/sessions` | 0 |
| 主人指令 | `/metrics` `/plugins` `/reload [名]` | 0 |

---

## 二、消息与会话

| 功能 | 说明 | Token |
|------|------|------:|
| 群未 @ | 只缓存，不调模型 | 0 |
| 群 @ / 私聊 | 进 Agent Loop | 按轮 |
| 语音转写 | NapCat ASR 文本 | 0 |
| 表情/图片标签 | 缓存写入标签化描述 | 0 |
| 滚动摘要 | ≥30 条时压早期记录 | 极少 |
| 用户冷却 | 约 3s | 0 |
| 并发信号量 | 默认 3 | — |
| 「退出」 | 清会话不杀进程 | 0 |
| 待办短句 | 直查 SQLite | 0 |
| Prompt 注入隔离 | `<untrusted_content>` | 0 |

---

## 三、文件（智能资产库）

| 功能 | 说明 | Token |
|------|------|------:|
| 未 @ 静默登记 | 下载+索引，无摘要 | 0 |
| @ / 无 caption 摘要 | LLM 摘要 + 标签 JSON | 极少 |
| 规则标签 + LLM 标签合并 | `files/tags` + enrich | 0/极少 |
| 回执元数据 | 类型 · 大小 · 时间 · #标签 | 0 |
| 自然语言检索 | 「上次那个PDF」→ nl_search | 0 |
| 保存上面的文件 | 回捞近期附件 | 极少 |
| SHA256 去重 | `_blobs/` 复用 | 0 |
| 引用计数 GC | `ref_count==0` 才删物理文件 | 0 |
| 自动标签 | 发票/合同/简历/代码… | 0 |
| 群调私聊文件 | 跨作用域检索发送 | 一轮 |
| 有哪些文件 | 私聊发 list | 0 |
| 删除需确认 | 说明用途后确认 | 0 |

---

## 四、记忆 / 催办 / 搜索 / 增量知识卡片

| 功能 | 说明 | Token |
|------|------|------:|
| 多租户隔离 | `private_{uid}` / `group_{gid}` | — |
| 情景/语义分层 | episodic / semantic | — |
| 记忆意图门控 | 默认 LLM 短分类（`QQ_INTENT_GATE=llm`）；失败回退正则；闲聊不注入 | 极少 |
| 召回硬阈值 | `QQ_RECALL_MIN_SCORE` 低于则丢弃 | 0 |
| 结构化用户画像 | `profile.json` 偏好/日期/备注，注入 Prompt | 0 |
| 对话后 harvest | 后台判断是否写入记忆/画像 | 极少 |
| 导出日历 ICS | 「导出日历」 | 0 |
| 用量统计 | 「用量」/metrics → usage.db | 0 |
| 消息处理队列 | 有界 queue + worker，防刷屏打爆 | 0 |
| 结构化日志 | JSON 一行 event | 0 |
| **增量语义归纳** | 提炼 JSON → 向量对齐 → Upsert/Merge | 1–2 轮 |
| 知识卡片 | `归纳一下 …` / `synthesize_knowledge` | 极少 |
| 冲突合并 | 相似度 ≥ 阈值则 LLM Merge 旧卡 | 1 轮 |
| 访问衰减 | access_count / last_accessed | 0 |
| 自动归档 | 低价值情景 archived | 0 |
| 后台归纳 | 每 6h + 03:30 情景→卡片 | 极少 |
| 可替换嵌入 | fastembed 可选，默认哈希 | — |
| 催办 | APScheduler 多点 tick | 创建时 1 轮 |
| 时区 | Asia/Shanghai，落库 UTC | 0 |
| 重启补发 | 过期 pending 立刻催 | 0 |
| 早报 | 查今日待办私聊主人 | 0 |
| 关键词提醒 | 群聊正则 → 私聊 | 0 |
| web_search | 联网搜索 | 一轮 |
| fetch_url / 预取链接 | 打开帖子/网页抽正文（Reddit 走 JSON）；用户贴 URL 时自动预取再总结 | 一轮 |

---

## 五、生活助手（Phase 2）

| 说法 | 行为 | Token |
|------|------|------:|
| `记一下 周末爬山` | 闪念入库（自动标签） | 0 |
| `闪念列表` / `有哪些闪念` | 列出最近闪念 | 0 |
| `找闪念 爬山` | 语义/召回检索 | 0 |
| `午饭 25 元` | 记账（餐饮等分类） | 0 |
| `本周花了多少` / `今天花了多少` | 按窗口统计 + 最近几笔 | 0 |
| `最近账单` | 账单列表 | 0 |
| `今日速递` | RSS + 可选 GitHub Release | 0* |
| 定时速递 | `QQ_DIGEST_HOUR` 私聊主人 | 0* |

\* `QQ_DIGEST_USE_LLM=1` 时才会精简烧 Token。  
OCR / 图表看板：**后置**。

---

## 六、插件与架构（Phase 3）

| 功能 | 说明 |
|------|------|
| `plugins/` 热加载 | importlib 扫描 + manifest |
| 示例 `echo` | 演示注册工具 |
| `/plugins` | 列出插件（主人） |
| `/reload echo` | 热重载插件（主人） |
| Admin `/plugins/{name}/reload` | HTTP 重载 |

---

## 七、Vault + 控制台（Phase 4）

| 功能 | 说明 | Token |
|------|------|------:|
| Obsidian 监听入库 | watchdog → 切片 → vault.db | 0 |
| AI 写笔记 | `写一篇关于…的笔记` / `write_vault_note` | 1 轮 |
| Vault 检索 | `在知识库搜…` / `search_vault` | 0 |
| Git commit / 可选 push | 写笔记后自动 | 0 |
| Magic Link | 任意用户私聊「打开控制台」→ 只看自己的数据 | 0 |
| Dashboard SPA | 待办看板 · 知识图 · 记忆检索 | 0 |

详见 [vault-dashboard.md](./vault-dashboard.md)。

---

## 八、QQ 工具白名单

记忆 · 知识卡片 · 催办 · 文件 · 搜索 · Vault  
**无** bash / edit / Task DAG / MCP  

可选 Coding CLI：`python -m agent.main`（与 QQ 隔离）。

---

## 后置（尚未做）

- PDF/DOCX 全文切片 RAG  
- sqlite-vec 替换 Python 余弦扫描  
- 图片 OCR / 多模态发票  
- 公网 HTTPS Dashboard  
- 全面 asyncio + Redis  
