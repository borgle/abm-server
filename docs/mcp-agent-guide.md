# Agent MCP 安装与接入指南

ABM Server 实现标准 **MCP Streamable HTTP** 协议，内置 **OAuth 2.1（Authorization Code + PKCE + 动态客户端注册）**。MCP 客户端无需在配置文件中硬编码任何 API Key。

---

## 1. 前置准备

1. 启动 `abm-server` 并登录 Web 控制台（`/console/connections`）。
2. 创建一把 `abm_` API Key，在 Chrome 浏览器安装 ABM 扩展并粘贴该 Key，确认连接状态显示为**在线**。
3. 复制你的 MCP 服务端入口地址：
   - 认证入口（完整工具集）：`https://<your-server>/mcp`
   - 公开入口（仅公开工具）：`https://<your-server>/mcp/public`

---

## 2. 常见 MCP 客户端配置

### 2.1 Claude Code
```bash
claude mcp add --transport http abm https://<your-server>/mcp
```

### 2.2 Codex CLI
在 `~/.codex/config.toml` 中添加：
```toml
[mcp_servers.abm]
url = "https://<your-server>/mcp"
```

### 2.3 Cursor / Windsurf / 通用 HTTP MCP 客户端
```json
{
  "mcpServers": {
    "abm": {
      "type": "http",
      "url": "https://<your-server>/mcp"
    }
  }
}
```

首次连接时，客户端会自动发现 `/.well-known/oauth-protected-resource` 与 `/.well-known/oauth-authorization-server`，完成动态客户端注册并弹出浏览器授权页面（`/oauth/authorize`）。

---

## 3. OAuth Scope 与浏览器连接策略

在 `/oauth/authorize` 授权页，用户可以选择：
- **Scopes**：
  - `browser`：调用全部 `browser_*` 浏览器自动化工具与视频投递工具。
  - `account:read`：读取当前账号信息、API Key 列表、连接状态与用量统计。
  - `account:write`：创建或吊销 API Key。
- **浏览器连接绑定策略（Connection Policy）**：
  - `auto`（默认）：自动路由到当前账号下空闲的在线浏览器连接。
  - `pinned`：固定绑定到指定的单个 API Key 连接。
  - `allowlist`：仅允许在勾选的一组连接中分配会话。

---

## 4. 多任务并发与会话租约（`browserSessionId`）

当账号下存在多个连接或多任务并行时：
1. 先调用 `browser_open_session` 获取独占的 `browserSessionId`。
2. 在后续 `browser_navigate`、`browser_click`、`browser_evaluate` 等工具调用中传入该 `browserSessionId`。
3. 任务结束后调用 `browser_close_session` 释放租约（未主动释放的租约会在 `ABM_MCP_SESSION_LEASE_TTL_SECONDS` 后自动回收）。

---

## 5. 常见错误码与恢复动作

| 错误码 | 含义 | 客户端建议恢复动作 |
|---|---|---|
| `ABM_EXTENSION_OFFLINE` | 当前账号没有在线的浏览器扩展连接 | 提示用户打开 Chrome 并检查扩展连接状态 |
| `ABM_CONNECTION_BUSY` | 目标连接的并发会话槽位已满 | 等待现有任务完成、调用 `browser_close_session` 或增加连接 |
| `ABM_SESSION_REQUIRED` | 多连接场景下未传 `browserSessionId` | 先调用 `browser_open_session` 获取会话 ID |
| `ABM_VIDEO_PERMISSION_REQUIRED` | 扩展缺少视频源域名的下载权限 | 提示用户在扩展弹窗中授权目标域名 |
| `ABM_QUOTA_EXCEEDED` | 触发工具调用或视频中转硬额度上限 | 在控制台查看用量或调整配额设置 |
