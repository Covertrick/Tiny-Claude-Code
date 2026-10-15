# Phase 4：Vault Sync + Magic Link 控制台

个人知识管理（PKM）与可视化控制中枢。两套流水线可独立启用。

---

## 模块一：Obsidian / Markdown Vault

### 工作流

```text
Obsidian Vault 目录
    │ watchdog 监听 .md
    ▼
增量解析 Frontmatter + 切片
    ▼
SQLite（vault.db）+ 本地嵌入（与记忆共用 embedder）
    ▲
QQ「写一篇关于…的笔记」→ LLM 生成 MD → 安全写入 → Git commit
```

**刻意未绑死 sqlite-vec**：当前与 `knowledge` 一样用 Python 余弦检索；接口留在 `VaultIndex`，装扩展后可替换存储层。

### 配置

```env
QQ_VAULT_PATH=D:/Obsidian/MyVault   # 必填才启用
QQ_VAULT_WATCH=1
QQ_VAULT_GIT_COMMIT=1
QQ_VAULT_GIT_PUSH=0                 # 需已配置 origin
QQ_VAULT_NOTES_SUBDIR=QQ Agent
QQ_VAULT_REINDEX_ON_START=0         # 1=启动全量扫库
```

依赖：

```bash
pip install watchdog GitPython
```

### QQ 话术

| 说法 | 行为 |
|------|------|
| `写一篇关于 Python 异步的笔记` | 生成 MD → 写入 Vault → 索引 → Git |
| `在知识库搜 异步` | 语义检索笔记块 |
| `重建索引` / `扫描知识库` | 主人全量 reindex（可较慢） |

工具：`write_vault_note` / `search_vault`。路径经 `os.path`/`relative_to` 校验，禁止写出 Vault 根外。

落盘：`agent/.runtime/qq/vault.db`；笔记默认 `Vault/QQ Agent/YYYY-MM-DD-主题.md`。

---

## 模块二：Magic Link Dashboard

### 原理

1. `QQ_ADMIN_PORT=8787` 启动 FastAPI（后台线程）
2. **任意用户**私聊「打开控制台」→ 按该用户 QQ 签发限时 Token（默认 15 分钟）
3. 默认用 **Cloudflare Quick Tunnel** 给出 `https://*.trycloudflare.com` 公网链接（手机流量也能开，不必同一 WiFi）
4. 打开链接写入 Cookie；面板只读该用户数据；SPA 已做手机适配

`QQ_OWNER_QQ` 仍只用于早报/关键词等，**不是**控制台门槛。

### 配置

```env
QQ_ADMIN_PORT=8787
QQ_ADMIN_MAGIC_TTL=900
QQ_ADMIN_TUNNEL=cloudflare   # off 则仅局域网
# QQ_ADMIN_PUBLIC_URL=https://xxx    # 有固定域名可覆盖
```

```bash
pip install fastapi uvicorn itsdangerous
```

### 面板能力

| 区块 | 数据 |
|------|------|
| 指标卡 | 记忆条数 / Vault 文件数 / 嵌入后端 |
| 待办看板 | pending / done / cancelled，可点完成/取消 |
| 知识网络 | Vault 同 tag 共现图（ECharts force） |
| 记忆列表 | 语义检索当前用户记忆 |

API（均需 Cookie / token）：`/api/me` `/api/schedules` `/api/knowledge` `/api/vault` `/metrics`。

---

## 建议落地顺序

1. 先开 Dashboard：`QQ_ADMIN_PORT` + `QQ_ADMIN_TUNNEL=cloudflare` → 私聊「打开控制台」
2. 再挂 Vault：填 `QQ_VAULT_PATH` → `重建索引` → 试写一篇笔记
3. 需要语义质量时再 `QQ_EMBEDDING_BACKEND=fastembed`
