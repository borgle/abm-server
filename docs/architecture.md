# ABM Server 系统架构（Open-Source Core）

## 1. 定位与边界

`abm-server` 是连接 AI Agent（MCP 客户端）与用户真实浏览器的生产级服务端核心，同时作为开源单用户版本（`ABM_EDITION=single`）独立发行。

### 1.1 核心职责
- **单用户身份与凭证**：首次启动通过 `ABM_BOOTSTRAP_ADMIN_*` 初始化唯一管理员账号；提供 Argon2id 密码认证、Cookie 会话、邮箱验证、密码重置与多把 `abm_` API Key 管理。
- **扩展 WebSocket 网关（`abm/1`）**：维护 Chrome 扩展长连接、心跳保活、浏览器会话租约（`browserSessionId`）及 `browser_*` 工具调用分发。
- **MCP Streamable HTTP 与 OAuth 2.1**：内置 OAuth 2.1 授权服务器（动态客户端注册、PKCE S256、Refresh Token 轮换），在 `/mcp` 与 `/mcp/public` 提供标准 MCP 服务。
- **视频协调与字节桥（Video Bridge）**：支持 `url`（扩展直连下载）与 `bridge`（短期令牌 + 同源网页分片推送）双通道投递，视频字节不进入 WebSocket 且不在服务端持久化。
- **创作台（Creation Studio）**：选题雷达多引擎并行采集、来源库、AI 撰稿、配图生成、公众号内联样式 HTML 与小红书 3:4 卡片（Playwright 渲染）导出、发布计划。
- **统一存储与数据库迁移**：内置 `local` 与 `s3` 对象存储实现，以及基于 Alembic 的 SQLite / PostgreSQL 统一 Schema 迁移链。

---

## 2. 目录与领域包结构

```text
abm-server/
├── abm_server/
│   ├── main.py                  # FastAPI 应用装配、生命周期与中间件
│   ├── config.py                # Pydantic Settings (ABM_* 环境变量)
│   ├── database.py              # SQLAlchemy AsyncEngine 与会话工厂
│   ├── migrate.py               # abm-server-migrate CLI 入口
│   ├── editions.py              # 发行版能力矩阵 (SINGLE / HOSTED) 与路由门禁
│   ├── quotas.py                # QuotaPolicy 协议与单用户 LocalQuotaPolicy
│   ├── tiers.py                 # 账号档位解析 (local 档位与托管扩展钩子)
│   ├── errors.py                # 统一 ABM_* 异常与 HTTP 错误响应格式
│   ├── concurrency.py           # 滑动窗口限流器与按 Key 异步互斥锁池
│   ├── logging.py               # 结构化日志配置
│   ├── schemas.py               # Pydantic 请求/响应 DTO
│   ├── accounts/                # 账号認證、Bootstrap 初始化、登录会话清理、一次性令牌
│   ├── admin/                   # 管理端服务
│   │   ├── creation_config.py   # 模型 Provider 加密存储 (AES-GCM) 与本机模型绑定
│   │   ├── system_config.py     # 运行时分组参数配置、校验与导入导出
│   │   └── service.py           # 托管注册审批开关扩展钩子
│   ├── api/                     # HTTP 路由层 (/api/v1/*)
│   │   ├── __init__.py          # 核心路由聚合与 abm_cloud.api 可选挂载
│   │   └── routes/              # auth, api_keys, admin, creation, creation_media,
│   │                            # extension_ws, notices, runtime, usage, video
│   ├── api_keys/                # abm_<prefix>_<secret> 摘要生成、校验与吊销
│   ├── audit/                   # 账号与管理操作审计事件写入
│   ├── auth/                    # Argon2id/SHA-256 安全原语、OAuth Scope、CSRF/Session 依赖
│   ├── creation/                # 创作台领域实现
│   │   ├── bindings.py          # 对话与图片模型解析 (本机配置 / 托管套餐扩展)
│   │   ├── compose.py           # 提示词组装与上下文构建
│   │   ├── generation.py        # 稿件生成管线与额度扣减
│   │   ├── images.py            # OpenAI Images 兼容生图与平台尺寸裁切
│   │   ├── media.py             # 媒体资产管理、去重与回收站
│   │   ├── layout.py            # Markdown AST 解析与公众号/小红书排版生成
│   │   ├── render.py            # Playwright 小红书卡片无头渲染
│   │   ├── exports.py           # 导出任务与 ZIP 打包
│   │   ├── publish.py           # 浏览器发布辅助与连接协调
│   │   ├── maintenance.py       # 过期导出与回收站清理
│   │   └── research/            # 选题雷达规划器、多引擎适配器与并行采集 Runner
│   ├── email/                   # log / SMTP 邮件通知服务
│   ├── extension_gateway/       # WebSocket 网关 (gateway.py) 与 abm/1 协议校验 (protocol.py)
│   ├── mcp/                     # MCP Streamable HTTP 服务、OAuth 2.1 授权与工具定义
│   ├── migrations/              # Alembic 迁移环境与版本脚本 (0001 ~ 0015)
│   ├── models/                  # SQLAlchemy ORM 实体定义
│   ├── notices/                 # 站内通知中心服务
│   ├── storage/                 # StorageBackend 协议、LocalStorage 与 S3Storage
│   ├── tools/                   # browser_* 浏览器工具 Schema 与契约
│   ├── usage/                   # 按日/按 Key 用量统计与阈值告警
│   ├── video/                   # 视频作业状态机、临时文件分片与短期桥接令牌
│   └── web/                     # Jinja2 服务端模板与静态模块化前端 (/static/*)
├── scripts/                     # 真实浏览器与视频桥端到端验证脚本
├── tests/                       # 单用户核心单元与集成测试套件
└── docs/                        # 架构与操作文档
```

---

## 3. 核心协议与接口契约

### 3.1 认证体系三分离
| 入口 | 认证方式 | 适用对象 | 安全约束 |
|---|---|---|---|
| `/api/v1/*`（控制台与创作台） | `abm_session` HttpOnly Cookie + `X-CSRF-Token` | 浏览器 Web 用户 | 写请求强制校验 CSRF Token 与 `Origin` |
| `/mcp` | OAuth 2.1 `Bearer <access_token>` | Claude Code / Cursor / Codex 等 Agent | 强制 PKCE S256；支持按连接授权策略（`auto` / `pinned` / `allowlist`） |
| `/ws` 與 `/api/v1/session/*` | `abm_<prefix>_<secret>` API Key | Chrome 浏览器扩展 | 数据库仅存 SHA-256 摘要；明文仅在创建时返回一次 |
| `/api/v1/video/*`（视频桥） | `abm_bridge_<token>` 短期桥接令牌 | 同源 `/video-bridge` 页面 | 由扩展凭 API Key 换取，仅限视频分片读取与状态上报 |

### 3.2 扩展 WebSocket 协议（`abm/1`）
- **Endpoint**：`GET /ws`（Subprotocol: `abm.v1`）
- **信封格式**：
  ```json
  {
    "v": "abm/1",
    "id": "msg_uuid",
    "type": "session.hello | session.ready | session.identify | session.ping | session.pong | tool.invoke | tool.result | notice.push | error",
    "payload": {}
  }
  ```
- **连接与会话租约**：
  - 同一 API Key 默认最多允许 `ABM_LOCAL_BROWSER_CONNECTIONS`（默认 5）个并发浏览器连接。
  - 每个连接支持 `ABM_LOCAL_BROWSER_SESSIONS`（默认 3）个并发任务租约，并预留 `ABM_LOCAL_RESERVED_PRIORITY_SLOTS`（默认 1）个高优先级槽位供发布任务使用。

### 3.3 Open-Core 扩展点契约
`abm-server` 通过以下受控扩展点与私有包 `abm-cloud` 解耦：
1. **发行版解析（`editions.py`）**：`ABM_EDITION=single` 返回 `SINGLE` 能力矩阵（关闭注册、多用户管理与套餐）；设为 `hosted` 时检查 `abm_cloud` 是否存在，缺失则拒绝启动。
2. **HTTP 路由挂载（`api/__init__.py`）**：可选导入 `abm_cloud.api.api_router`，挂载托管版管理后台与社交登录路由。
3. **配额策略（`quotas.py`）**：`single` 使用 `LocalQuotaPolicy`（读取 `ABM_LOCAL_*` 环境变量）；`hosted` 委托 `abm_cloud.plans.PlanQuotaPolicy`。
4. **模型绑定（`creation/bindings.py`）**：`single` 读取 `creation_config.local`；`hosted` 委托 `abm_cloud.plans` 按用户套餐解析。
5. **账号档位与开通（`tiers.py`、`accounts/service.py`、`admin/service.py`）**：`single` 固定为 `local` 档位并拒绝外部注册；`hosted` 委托 `abm_cloud.accounts`。
6. **MCP 管理工具（`mcp/service.py`）**：`admin_*` 工具调用委托 `abm_cloud.mcp.call_admin_tool`。
