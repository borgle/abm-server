# abm-server 文档索引

`abm-server` 是 ABM（**a browser mcp**）的**开源核心与单用户自托管发行版**（AGPL-3.0）。多租户注册审批、SaaS 套餐计费、第三方社交登录、多用户管理与审计后台属于私有托管工程 `abm-cloud`，不在本仓库中。

## 核心文档目录

| 文档 | 说明 |
|---|---|
| [architecture.md](architecture.md) | 系统架构、领域包边界、HTTP / MCP / WebSocket（`abm/1`）契约、安全模型与 Open-Core 扩展接口 |
| [detailed-design.md](detailed-design.md) | 核心模块实现细节、并发锁与限流、事务边界、本地配额策略（`LocalQuotaPolicy`）与故障恢复 |
| [data-flow.md](data-flow.md) | 端到端数据流：单用户初始化与登录、扩展连接与工具调用、MCP OAuth 2.1 授权、视频双通道投递 |
| [creation-studio.md](creation-studio.md) | 创作台完整架构：选题雷达、素材库、AI 撰稿、图片生成、对象存储、公众号/小红书排版导出与发布辅助 |
| [mcp-agent-guide.md](mcp-agent-guide.md) | MCP 客户端接入指南：OAuth 2.1 + PKCE 流程、Scope 权限、多会话租约与工具清单 |
| [local-mode.md](local-mode.md) | 单用户自托管与本机部署指南（Docker / SQLite / PostgreSQL / 本地与 S3 存储） |
| [ui-design-system.md](ui-design-system.md) | Web 控制台与工作台 UI 设计 Token、组件规范与双语（`zh` / `en`）国际化机制 |

## 架构维护准则

1. **包边界一致性**：文档中的模块路径必须与 `abm_server/` 源码结构严格对齐。
2. **协议契约先行**：修改公开 HTTP 路由、MCP 工具 Schema、`abm/1` WebSocket 信封、`ABM_*` 错误码或数据库迁移时，必须同步更新 `architecture.md` 与 `data-flow.md`。
3. **严禁反向依赖**：`abm-server` 只提供标准能力矩阵（`Edition`）与可选插件扩展点，不得对 `abm_cloud` 产生硬编码运行依赖。
