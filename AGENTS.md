# ABM 开发指南（开源 Core / 单用户版 `abm-server`）

## 开始前必读

ABM 是 **a browser mcp** 的简称。修改代码前请先阅读：

1. `docs/README.md`：文档索引与仓库职责边界。
2. `docs/architecture.md`：系统分层、包结构、HTTP / MCP / WebSocket（`abm/1`）契约与扩展接口。
3. `docs/detailed-design.md`：并发锁、事务边界、安全与故障恢复设计。
4. `docs/data-flow.md` 与 `docs/creation-studio.md`：核心端到端数据流与创作台架构。

## 项目范围

本仓库是开源的 Core / 单用户自托管版本（`ABM_EDITION=single`），实现：

- 单用户账号 Bootstrap、登录会话、密码找回、邮箱验证与 `abm_` API Key。
- 浏览器扩展 WebSocket 网关（`abm/1`）与会话租约调度。
- 标准 MCP Streamable HTTP 与内置 OAuth 2.1（PKCE + 动态客户端注册）。
- 浏览器工具路由（`browser_*`）与视频双通道投递（`url` / `bridge`）。
- 创作台（选题雷达、素材库、AI 撰稿、图片生成、公众号/小红书排版导出、发布辅助）与对象存储（`local` / `s3`）。
- Web 控制台、单用户模型绑定（`/admin/plans`）与运行时参数配置（`/admin/config`）。

多用户注册审批、SaaS 套餐计费、第三方社交登录、多用户管理与审计后台属于私有仓库 `abm-cloud`，不在本仓库实现。

## 强制命名

- 发行包：`abm-server`
- Python 包：`abm_server`
- 服务命令：`abm-server`
- 迁移命令：`abm-server-migrate`
- MCP 服务名：`abm-browser-mcp`
- 环境变量：`ABM_*`
- API Key：`abm_<prefix>_<secret>`
- 业务错误：`ABM_*`
- 浏览器工具：`browser_*`
- 扩展协议：`abm/1`

## 架构规则

- 保持领域包边界清晰：`accounts/`、`admin/`、`api/`、`api_keys/`、`audit/`、`auth/`、`creation/`、`email/`、`extension_gateway/`、`mcp/`、`models/`、`notices/`、`storage/`、`tools/`、`usage/`、`video/`、`web/` 各司其职，不在顶层堆放冗余重导出垫片。
- 托管能力只能通过受控扩展点（`editions.py`、`quotas.py`、`tiers.py`、`creation/bindings.py`、`accounts/service.py`、`admin/service.py`、`api/__init__.py`、`mcp/service.py`）以可选导入方式接入，严禁在 core 中硬依赖 `abm_cloud`。
- Web 页面默认跟随客户端语言（仅 `zh` / `en`，其他回退 `en`），用户选择保存在 `abm.lang`。
- MCP 工具描述、工具结果以及 HTTP/OAuth 错误消息统一使用英文规范文案。
- `/mcp` 只接受 OAuth 2.1；API Key 只用于扩展 WebSocket，并由扩展换取短期视频桥令牌。
- 路由层负责校验和转换 HTTP 输入；领域行为由服务层实现。

## 安全与数据库规则

- 密码使用 Argon2id；API Key、会话令牌、CSRF 令牌与一次性验证令牌只存 SHA-256 摘要；模型 Provider 密钥使用 AES-GCM 加密存储。
- Cookie 认证的写接口必须通过 `require_csrf` 校验 CSRF 与 Origin。
- 凭证或账号失效后必须吊销会话并主动关闭对应 WebSocket 连接。
- 数据库迁移脚本位于 `abm_server/migrations/`，由本仓库唯一维护，模型与查询必须兼容 SQLite 与 PostgreSQL。

## 开发与验证命令

```bash
python -m pip install -e ".[dev]"
abm-server-migrate
python -m pytest
python -m ruff check .
python -m ruff format --check .
```
