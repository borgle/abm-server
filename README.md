# ABM（a browser mcp） Server

ABM 是 **a browser mcp** 的简称。本仓库是 ABM 的**开源核心与单用户自托管服务端**（AGPL-3.0），用于将 MCP 客户端安全连接到用户自己的浏览器，并提供完整的 AI 创作与多平台排版工作台。

## 核心能力

- **单用户自托管账号体系**：首次启动通过 `ABM_BOOTSTRAP_ADMIN_*` 自动创建唯一管理员账号，关闭公开注册与第三方社交建号；支持 Argon2id 密码认证、邮箱验证、密码重置、会话管理、数据导出与多把 `abm_` API Key 管理。
- **内置 OAuth 2.1 的标准 MCP 服务**：支持 Streamable HTTP（`/mcp`、`/mcp/public`）、Authorization Code + PKCE S256、动态客户端注册及连接级授权策略（`auto` / `pinned` / `allowlist`）。
- **浏览器扩展 WebSocket 网关（`abm/1`）**：提供 23 个 `browser_*` 浏览器自动化工具、并发连接管理、独占会话租约（`browserSessionId`）与发布高优先级预留槽位。
- **双通道视频投递（`url` / `bridge`）**：远程 URL 视频由扩展直连下载；本机或 Base64 视频通过短期令牌（`abm_bridge_*`）与临时文件分片桥接推送，服务端不持久化视频字节。
- **创作台（Creation Studio）**：包含选题雷达（多引擎并行搜索、验证码暂停恢复）、素材库、AI 撰稿、OpenAI Images 兼容生图與参考图改图、微信公众号内联 HTML 导出、小红书 3:4 卡片（Playwright 渲染）导出与浏览器辅助发布。
- **单用户本地配额（`LocalQuotaPolicy`）**：通过 `ABM_LOCAL_*` 环境变量配置本机并发连接数与内容额度（内容额度默认无限制）。

> 多租户注册审批、SaaS 套餐与配额、第三方社交登录、用户管理与审计后台属于私有托管版 `abm-cloud`，不在本开源仓库中。

---

## 目录结构

```text
abm-server/
├── abm_server/
│   ├── main.py                # FastAPI 应用装配与生命周期
│   ├── config.py              # ABM_* 环境变量配置
│   ├── database.py            # SQLite / PostgreSQL 异步数据库引擎
│   ├── migrate.py             # abm-server-migrate 迁移 CLI
│   ├── editions.py            # 发行版能力矩阵 (single / hosted)
│   ├── quotas.py              # QuotaPolicy 协议与 LocalQuotaPolicy
│   ├── tiers.py               # 账号档位解析
│   ├── accounts/              # 账号认证、会话管理与一次性令牌
│   ├── admin/                 # 模型 Provider 加密配置与系统参数管理
│   ├── api/                   # /api/v1/* HTTP 路由层
│   ├── api_keys/              # abm_ API Key 生成与吊销
│   ├── audit/                 # 审计事件记录
│   ├── auth/                  # 密码哈希、CSRF 与 OAuth Scope 依赖
│   ├── creation/              # 创作台 (雷达、撰稿、生图、排版渲染、导出、发布)
│   ├── email/                 # 邮件发送服务 (log / smtp)
│   ├── extension_gateway/     # 扩展 WebSocket 网关与 abm/1 协议
│   ├── mcp/                   # MCP Streamable HTTP 与 OAuth 2.1 服务
│   ├── migrations/            # Alembic 数据库迁移脚本
│   ├── models/                # SQLAlchemy ORM 模型
│   ├── notices/               # 站内通知服务
│   ├── storage/               # 本地与 S3 兼容对象存储
│   ├── tools/                 # 浏览器工具 Schema 定义
│   ├── usage/                 # 用量统计与阈值告警
│   ├── video/                 # 视频作业协调与分片桥接
│   └── web/                   # Jinja2 模板与前端静态资源
├── docs/                      # 架构与使用文档
├── scripts/                   # 端到端实时验证脚本
└── tests/                     # 自动化测试套件
```

---

## 文档导航

完整文档索引见 [docs/README.md](docs/README.md)：
- [系统架构设计](docs/architecture.md)
- [详细设计与并发边界](docs/detailed-design.md)
- [端到端数据流](docs/data-flow.md)
- [创作台与媒体排版指南](docs/creation-studio.md)
- [Agent MCP 接入指南](docs/mcp-agent-guide.md)
- [单用户本地部署指南](docs/local-mode.md)
- [UI 设计系统与国际化规范](docs/ui-design-system.md)
- [开发者规范](AGENTS.md)

---

## 本地开发与测试

```bash
python -m pip install -e ".[dev,render]"
abm-server-migrate
python -m pytest
python -m ruff check .
abm-server
```

## Docker 部署

```bash
cp .env.docker.example .env
docker compose up -d --build
```

本机 HTTP 快速体验可使用：
```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

## 许可证

本项目基于 [AGPL-3.0-or-later](LICENSE) 开源发布。
