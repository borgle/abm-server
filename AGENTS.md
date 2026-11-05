# ABM 开发指南（开源 core）

## 开始前必读

ABM 是 **a browser mcp** 的简称。

修改代码前先阅读：

1. `docs/README.md`：文档索引和本仓库范围。
2. `docs/architecture.md`：完整系统契约。
3. `docs/detailed-design.md`：模块实现与并发/事务边界。
4. `docs/data-flow.md` 与 `docs/scenarios.md`：端到端链路和验收场景。
5. 当前模块的 README 与测试。

## 项目范围

本仓库是开源的 core / 单用户版，实现：

- 单用户账号、登录会话和 API Key。
- 扩展 WebSocket 网关。
- 标准 MCP Streamable HTTP（OAuth 2.1）。
- 浏览器工具路由与服务端工具。
- 视频作业协调与下载投递。
- 创作台、对象存储与公众号 / 小红书导出。
- 用户 Web 控制台和单用户系统设置。

多用户注册审批、套餐、计费、社交登录、用户管理和审计后台属于私有 `abm-cloud`，不在本仓库。

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

不得引入其他产品前缀，也不得在协议模块之外复制协议常量。

## 架构规则

- 账号 API、持久化、认证、MCP、扩展网关、视频协调和审计保持独立包边界。
- Web 页面默认跟随客户端语言（仅 zh / en，其他回退 en），用户选择保存在 `abm.lang`。
- MCP 工具描述、工具结果以及 HTTP/OAuth 错误消息使用英文规范文案，客户端通过 `ABM_*` 错误码本地化。
- `/mcp` 只接受 OAuth 2.1；API Key 只用于扩展 WebSocket，并由扩展换取短期视频桥令牌。
- 多连接 OAuth 必须通过 `browser_open_session` 获取服务端生成的 `browserSessionId`，连接租约独占。
- 路由负责校验和转换 HTTP 输入；领域行为由服务层实现。
- 数据库访问通过仓储或服务边界，不在路由中直接拼查查询。
- MCP SDK 负责 JSON-RPC 封装与传输。
- 扩展网关负责 WebSocket 会话和 pending 调用状态。
- 视频作业按 `api_key_id` 归属，禁止跨 Key 暴露。
- URL 视频默认由扩展直连；bridge 只把在途数据写入临时文件，交付/失败/TTL 后删除，不做持久化存储。
- 本机大文件优先 `browser_set_files_native`，避免视频字节经过服务端。
- 实时连接、pending 调用和视频临时状态保持进程内或临时文件，除非后续明确引入共享状态设计。
- 托管能力只能通过可选导入接入，不得在 core 中直接依赖 `abm_cloud`。

## 安全规则

- 密码使用 Argon2id。
- 完整 API Key 只保存 SHA-256 摘要。
- API Key 明文只在创建响应中返回。
- 不记录密码、会话令牌、CSRF 令牌、API Key 秘密或视频字节。
- 账号会话要求账号状态为 `active`，运行 API 要求 API Key 状态有效。
- Cookie 认证的写接口必须校验 CSRF 与 Origin。
- 凭证或账号失效后吊销会话并关闭对应 WebSocket。
- 邮箱验证和密码重置 token 只保存摘要、一次性使用并设置短有效期。
- 删除账号必须校验当前密码和 CSRF；最后一个管理员不能删除。
- WebSocket 只使用标准关闭码，业务原因通过 `ABM_*` 错误表达。

## 数据库规则

- 迁移脚本位于 `abm_server/migrations/`，通过 `abm-server-migrate` 执行。
- schema 由 core 维护；托管版共用同一套迁移，不另建迁移链。
- 模型和查询必须保持 SQLite 与 PostgreSQL 可移植。
- 时间统一使用带时区的 UTC。
- 为凭证查询、归属、状态筛选和审计查询建立索引。
- 不存储任何明文凭证。
- 测试使用隔离临时数据库，不依赖本地开发数据库。

## 协议规则

- 公共消息类型和字段遵循 `docs/architecture.md`。
- 分发前必须校验 `abm/1` 信封。
- 工具调用、通知、pending 请求和视频作业必须保持精确的 `api_key_id` 归属。
- 协议变化必须同时完成：
  1. 更新 `docs/architecture.md`、`docs/data-flow.md` 与相关场景。
  2. 更新服务端契约测试。
  3. 更新扩展契约测试。

## 开发流程

1. 确定所属模块和公开契约。
2. 先添加能够表达目标行为的测试。
3. 实现最小且完整的改动。
4. 执行格式化、静态检查和聚焦测试。
5. 涉及协议、认证、数据库或路由时执行完整测试。
6. 需要时在同一次提交中更新文档和数据库变更。

常用命令：

```bash
python -m pip install -e ".[dev]"
abm-server-migrate
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## 完成标准

- 行为符合架构契约。
- 新增路径具有成功、校验、授权和失败测试。
- 数据库变更可以从空库执行。
- 凭证保持脱敏。
- 现有测试全部通过。
- 文档与实现接口一致。
- 提交只发生在本仓库。
