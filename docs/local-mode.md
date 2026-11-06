# 单用户本机与自托管部署指南（Local Mode）

`abm-server` 默认以单用户模式（`ABM_EDITION=single`）运行，所有账号、会话、采集素材与创作资产均保存在用户自己的机器或私有服务器上。

---

## 1. 快速启动（本地 Python 环境）

```bash
# 1. 安装依赖（含 Playwright 卡片渲染支持）
python -m pip install -e ".[dev,render]"
python -m playwright install chromium

# 2. 配置环境变量并执行数据库迁移
export ABM_EDITION=single
export ABM_SESSION_COOKIE_SECURE=false
export ABM_BOOTSTRAP_ADMIN_EMAIL=admin@localhost
export ABM_BOOTSTRAP_ADMIN_PASSWORD=local-admin-password
export ABM_CREATION_SECRET_KEY=$(python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

abm-server-migrate

# 3. 启动服务（默认监听 http://0.0.0.0:18050）
abm-server
```

---

## 2. Docker Compose 部署

### 2.1 本机 HTTP 模式（`localhost` / `127.0.0.1`）
适用于在本机直接运行 Docker 并连接本机 Chrome 扩展：
```bash
cp .env.example .env
# 在 .env 中填入 ABM_CREATION_SECRET_KEY
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

### 2.2 生产 HTTPS 模式（反向代理 / Cloudflare Tunnel）
适用于部署在私有云服务器并通过域名提供 HTTPS 访问：
```bash
cp .env.docker.example .env
# 修改 .env 中的 ABM_BOOTSTRAP_ADMIN_EMAIL、ABM_BOOTSTRAP_ADMIN_PASSWORD、ABM_PUBLIC_BASE_URL 与 ABM_CREATION_SECRET_KEY
docker compose up -d --build
```
> **注意**：通过反向代理访问时，请保持 `ABM_SESSION_COOKIE_SECURE=true` 并设置 `ABM_FORWARDED_ALLOW_IPS=*`。

---

## 3. 单用户本地配额与模型配置

### 3.1 配置本机大模型与生图模型
1. 使用 `ABM_BOOTSTRAP_ADMIN_*` 账号登录 `/admin/plans`（单用户版显示为**本机模型**）。
2. 在右侧「模型连接」点击**新增**，填入 OpenAI 兼容接口的 Base URL 与 API Key（如 DeepSeek、OpenAI、本地 Ollama / vLLM），点击**测试**验证连通性。
3. 在左侧卡片绑定默认对话模型、备用模型与图片生成模型，点击**保存配置**。

### 3.2 本地额度环境变量（`ABM_LOCAL_*`）
单用户版不启用 SaaS 套餐限制，内容额度默认不设上限（`0` 表示不限制），也可通过环境变量自行设定护栏：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `ABM_LOCAL_GENERATIONS_PER_DAY` | `0` | 每日 AI 稿件生成次数上限（0 为不限） |
| `ABM_LOCAL_TOKENS_PER_MONTH` | `0` | 每月内置模型 Token 上限（0 为不限） |
| `ABM_LOCAL_IMAGES_PER_DAY` | `0` | 每日 AI 生图张数上限（0 为不限） |
| `ABM_LOCAL_IMAGE_MAX_N` | `4` | 单次请求最大生图张数（1~4） |
| `ABM_LOCAL_STORAGE_BYTES` | `0` | 创作媒体存储总字节上限（0 为不限） |
| `ABM_LOCAL_RESEARCH_PAGES_PER_MONTH` | `0` | 每月选题雷达采集页数上限（0 为不限） |
| `ABM_LOCAL_BROWSER_CONNECTIONS` | `5` | 单个 API Key 允许同时在线的浏览器数 |
| `ABM_LOCAL_BROWSER_SESSIONS` | `3` | 单个浏览器连接允许并行的会话租约数 |
| `ABM_LOCAL_RESERVED_PRIORITY_SLOTS` | `1` | 为发布任务预留的高优先级会话槽位数 |
