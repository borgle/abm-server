# ABM Server MCP 安装使用手册

面向 Agent、MCP 客户端维护者和自动化集成方。ABM（a browser mcp）把用户自己的 Chrome 浏览器接入 MCP：浏览器工具由浏览器扩展在本机执行，服务端负责认证、授权、路由和审计。

## 1. 端点与能力

| 端点 | 认证 | 用途 |
|---|---|---|
| `/mcp` | OAuth 2.1 | 完整 MCP 工具，包括浏览器、账号和可用的管理员工具 |
| `/mcp/public` | 无 | 仅 `account_register`，用于 Agent 自助提交注册申请 |
| `/.well-known/oauth-protected-resource/mcp` | 无 | MCP 受保护资源元数据 |
| `/.well-known/oauth-authorization-server` | 无 | OAuth 授权服务器元数据 |
| `/docs/mcp` | 无 | 浏览器可读版本的本手册 |
| `/` | 无 | Chrome 扩展 landing page |

公共 `/mcp/public` 端点会按客户端 IP 限流。注册结果不会暴露邮箱是否已经存在。

## 2. 快速开始

### 2.1 安装 Chrome 扩展

ABM 扩展尚未上架 Chrome Web Store。请从 GitHub Releases 下载最新 ZIP：

```text
https://github.com/borgle/browser-mcp-extension/releases/latest
```

解压后：

1. 打开 `chrome://extensions`。
2. 开启右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”，选择解压目录。
4. 打开扩展选项页，填写 ABM 服务地址和 API Key。

### 2.2 注册账号

可以通过网页 `/register` 注册，也可以让 Agent 调用公共 MCP 端点：

```http
POST /mcp/public
Content-Type: application/json
Accept: application/json, text/event-stream

{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":"2025-03-26",
  "capabilities":{},
  "clientInfo":{"name":"agent","version":"1.0"}
}}
```

初始化后调用 `tools/call`：

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "account_register",
    "arguments": {
      "email": "user@example.com",
      "password": "至少十个字符",
      "displayName": "Ada",
      "applicationNote": "使用场景说明"
    }
  }
}
```

如果开启注册审批，新账号状态为 `pending`，需要管理员在 `/admin` 审批。

### 2.3 创建 API Key 并连接扩展

1. 登录 `/console`。
2. 创建 API Key。明文只在创建响应的 `plaintext` 字段中出现一次。
3. 点击“连接扩展”：控制台通过受信外部消息把服务器地址和 Key 写入扩展，并立即发起连接。
4. 在“连接你的 Agent”面板选择客户端，复制生成的配置：

```bash
# Claude Code
claude mcp add --transport http abm https://<server>/mcp

# Codex CLI
codex mcp add abm --url https://<server>/mcp
codex mcp login abm
```

Cursor / Windsurf 或通用客户端使用：

```json
{
  "mcpServers": {
    "abm": {
      "type": "http",
      "url": "https://<server>/mcp"
    }
  }
}
```

远程 MCP 使用 OAuth，首次连接会打开 ABM 授权页；不需要把 API Key 填进 MCP 客户端配置。

OAuth 认证的 MCP 调用在首次浏览器任务中通过 `browser_open_session` 获取 `browserSessionId`，该句柄独占一个在线扩展连接；后续调用携带句柄保持在同一连接上。没有在线连接时返回 `ABM_EXTENSION_OFFLINE`，连接已被其他任务占用时返回 `ABM_CONNECTION_BUSY`。

## 3. 认证

### 3.1 OAuth 2.1（推荐）

MCP 客户端连接 `/mcp` 时，如果未携带凭证，会收到 `401` 和：

```http
WWW-Authenticate: Bearer resource_metadata="https://<server>/.well-known/oauth-protected-resource/mcp", error="invalid_token", error_description="ABM_INVALID_TOKEN"
```

客户端应执行标准 MCP OAuth 流程：

1. GET `/.well-known/oauth-protected-resource/mcp`，读取 `resource` 和 `authorization_servers`。
2. GET `/.well-known/oauth-authorization-server`，读取授权、令牌、注册和吊销端点。
3. POST `/register` 动态注册 public client。
4. 使用 Authorization Code + PKCE (S256) 打开 `/authorize`。
5. 用户在 ABM 登录页登录，并在同意页确认客户端和 scopes。
6. POST `/token` 交换 access token 和 refresh token。
7. 使用 `Authorization: Bearer <access_token>` 访问 `/mcp`。

支持的 scopes：

| Scope | 权限 |
|---|---|
| `browser` | 通过浏览器扩展执行 `browser_*` 工具 |
| `account:read` | 读取账号、套餐、API Key 元数据和审计信息 |
| `account:write` | 修改账号资料/密码、创建/吊销 API Key、管理员操作 |

动态注册的客户端按 public client 处理，`token_endpoint_auth_method` 固定为 `none`，使用 PKCE，不签发 client secret。非回环地址的 `redirect_uri` 必须使用 HTTPS。

OAuth 令牌只保存 SHA-256 摘要。access token 默认 1 小时，refresh token 默认 30 天。refresh token 使用后立即轮换。`/revoke` 支持 access token 和 refresh token，且对 public client 不要求 client secret。

OAuth 访问令牌映射到用户，并携带授权时选择的连接策略。浏览器任务通过 `browser_open_session` 获取服务端生成的 `browserSessionId`，该句柄独占一个连接，其他任务不能同时占用同一连接。没有在线连接时返回 `ABM_EXTENSION_OFFLINE`，连接已被占用时返回 `ABM_CONNECTION_BUSY`。

### 3.2 认证失败

| 场景 | HTTP | 错误码 |
|---|---|---|
| 缺少凭证 | 401 | `ABM_INVALID_TOKEN` |
| OAuth 令牌无效、过期或吊销 | 401 | `ABM_INVALID_TOKEN` |
| OAuth scope 不足 | 工具错误 | `ABM_SCOPE_REQUIRED` |
| 非管理员调用管理员工具 | 工具错误 | `ABM_ADMIN_REQUIRED` |

## 4. MCP 客户端配置

### 4.1 通用 HTTP 配置

```json
{
  "mcpServers": {
    "abm": {
      "type": "http",
      "url": "https://<server>/mcp"
    }
  }
}
```

支持 OAuth 的客户端会自动完成发现和登录。若客户端要求显式配置，可使用：

```json
{
  "mcpServers": {
    "abm": {
      "type": "http",
      "url": "https://<server>/mcp",
      "auth": {
        "type": "oauth",
        "resource_metadata": "https://<server>/.well-known/oauth-protected-resource/mcp"
      }
    }
  }
}
```

不同客户端的字段名可能不同，以客户端文档为准。

## 5. 工具目录

### 5.1 浏览器工具（23）

全部使用 `browser_*` 命名，需要 `browser` scope，并要求用户有在线扩展连接。`browser_open_session` 返回 `browserSessionId`，后续浏览器工具携带该句柄以独占一个连接；`browser_close_session` 释放句柄。`pinned` OAuth 可以直接使用固定连接，`pool` 和 `auto` 在没有唯一连接时应先创建句柄。

| 工具 | 能力 |
|---|---|
| `browser_inject_script` | 在页面主环境执行 JavaScript；页面 CSP 禁止 eval 时通过 CDP 兜底 |
| `browser_read_page_data` | 读取 window 点分路径数据 |
| `browser_navigate` | 导航标签并等待加载状态 |
| `browser_control` | 查询、更新、激活或关闭标签 |
| `browser_extract_data` | 提取元素、window 或 document 数据 |
| `browser_click` | 按选择器或文本点击元素 |
| `browser_fill` | 填充输入框和可编辑元素 |
| `browser_keyboard` | 发送键盘输入 |
| `browser_upload_file` | 注入单个 base64 文件 |
| `browser_set_files` | 注入多个 base64 文件 |
| `browser_set_files_from_urls` | 下载并注入多个文件 |
| `browser_wait_elements` | 等待选择器达到指定数量 |
| `browser_set_video_to_page` | 将暂存视频注入文件输入框 |
| `browser_download_video_from_url` | 下载视频到扩展暂存区 |
| `browser_network_intercept` | 抓取并检查网络请求 |
| `browser_mouse_click` | 执行 CDP 鼠标点击 |
| `browser_mouse_scroll` | 执行 CDP 滚轮滚动 |
| `browser_input_sequence` | 回放 CDP 输入事件序列 |
| `browser_set_files_native` | 通过 CDP 注入本地文件路径 |
| `browser_stage_video` | 通过服务端暂存并投递视频 |
| `browser_send_notice` | 向扩展推送通知 |
| `browser_open_session` | 创建浏览器任务句柄并独占连接 |
| `browser_close_session` | 释放浏览器任务句柄 |

### 5.2 账号与 API Key 工具（7）

| 工具 | 权限 | 能力 |
|---|---|---|
| `account_register` | 公共 | 提交注册申请；结果不暴露邮箱是否存在 |
| `account_me` | `account:read` | 读取当前账号、套餐、Key 数量、扩展连接状态和认证方式 |
| `account_update_profile` | `account:write` | 修改显示名称 |
| `account_change_password` | `account:write` | 修改密码，并吊销其他账号会话和 OAuth 凭证 |
| `api_key_list` | `account:read` | 列出 API Key 元数据，不返回明文 |
| `api_key_create` | `account:write` | 创建 API Key，并在本次响应中一次性返回明文 |
| `api_key_revoke` | `account:write` | 吊销 API Key，并关闭使用该 Key 的扩展连接 |

### 5.3 管理员工具（5）

仅管理员账号在 `tools/list` 中可见，调用时还会再次校验角色。

| 工具 | 能力 |
|---|---|
| `admin_list_users` | 按状态和关键词筛选账号 |
| `admin_update_user` | 修改状态、套餐、套餐到期时间或备注 |
| `admin_get_settings` | 读取系统设置 |
| `admin_update_settings` | 修改注册审批策略 |
| `admin_list_audit` | 读取账号审计事件 |

普通用户调用管理员工具会返回 `ABM_ADMIN_REQUIRED`。

## 6. 调用示例

### 6.1 读取账号

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "tools/call",
  "params": {
    "name": "account_me",
    "arguments": {}
  }
}
```

结构化结果包含：

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "displayName": "Ada",
    "role": "user",
    "status": "active",
    "planCode": "free",
    "apiKeyLimit": 2
  },
  "activeApiKeyCount": 1,
  "extensionConnected": true,
  "connectedApiKeyId": "uuid",
  "authKind": "oauth",
  "scopes": ["browser", "account:read"]
}
```

### 6.2 创建 API Key

```json
{
  "jsonrpc": "2.0",
  "id": 11,
  "method": "tools/call",
  "params": {
    "name": "api_key_create",
    "arguments": {"name": "Agent 工作浏览器"}
  }
}
```

返回中的 `plaintext` 只出现一次，立即写入扩展或密钥管理器。

### 6.3 浏览器操作

```json
{
  "jsonrpc": "2.0",
  "id": 12,
  "method": "tools/call",
  "params": {
    "name": "browser_navigate",
    "arguments": {
      "url": "https://example.com",
      "reuse": "site"
    }
  }
}
```

## 7. 错误与恢复

| 错误码 | 含义 | 建议动作 |
|---|---|---|
| `ABM_INVALID_TOKEN` | OAuth 令牌无效/过期 | 使用 refresh token 或重新登录授权 |
| `ABM_SCOPE_REQUIRED` | OAuth 授权缺少 scope | 重新授权并确认权限 |
| `ABM_ADMIN_REQUIRED` | 需要管理员账号 | 使用管理员账号或移除管理员调用 |
| `ABM_EXTENSION_OFFLINE` | 没有在线扩展连接 | 在扩展中填写 API Key 并连接 |
| `ABM_CONNECTION_BUSY` | 目标连接已被其他浏览器任务占用 | 等待其他任务结束或重试 |
| `ABM_BROWSER_SESSION_REQUIRED` | 多连接授权需要显式任务句柄 | 先调用 `browser_open_session` |
| `ABM_BROWSER_SESSION_INVALID` | 任务句柄不存在或已过期 | 重新调用 `browser_open_session` |
| `ABM_KEY_LIMIT_REACHED` | API Key 数量达到套餐上限 | 吊销旧 Key 或升级套餐 |
| `ABM_ACCOUNT_PENDING` | 账号等待审批 | 等待管理员审批 |
| `ABM_ACCOUNT_DISABLED` | 账号已停用 | 联系管理员 |
| `ABM_RATE_LIMITED` | 请求过于频繁 | 按 `retryAfter` 等待 |
| `ABM_OAUTH_REQUEST_INVALID` | 授权请求不存在或过期 | 从 MCP 客户端重新发起授权 |

工具错误使用 MCP `CallToolResult.isError=true`，并在 `structuredContent.error` 中携带 `code`、`message`、`retryable` 和 `action`。

## 8. 安全边界

- API Key 只保存在扩展本地存储和服务端摘要中，不暴露给页面脚本。
- OAuth 动态注册客户端使用 PKCE public client，不签发 client secret。
- OAuth 授权码、access token 和 refresh token 只保存 SHA-256 摘要。
- 授权码一次性使用；refresh token 使用后轮换；吊销立即生效。
- 浏览器工具必须通过用户在线扩展执行；服务端不保存账号密码或页面 Cookie。
- 管理员操作记录审计事件；账号停用会吊销会话、OAuth 令牌并关闭扩展连接。
- 生产环境必须使用 HTTPS，并设置 `ABM_PUBLIC_BASE_URL` 或 `ABM_OAUTH_ISSUER_URL`。
- 公共注册端点按 IP 限流；注册响应不泄露邮箱是否存在。

## 9. 排查

### MCP 客户端没有弹出登录页

- 确认客户端支持 OAuth 和 Streamable HTTP。
- 确认 `/mcp` 未认证时返回 `401` 和 `WWW-Authenticate`。
- 确认客户端能访问 `/.well-known/oauth-protected-resource/mcp`。

### 浏览器工具返回扩展离线

OAuth 登录只解决 MCP 认证，浏览器工具仍需要扩展在线。请在 `/console` 创建 API Key，在扩展中连接，或确认已有在线连接。

### 授权后令牌仍无效

- 检查服务器时间。
- 检查 `ABM_OAUTH_ISSUER_URL` 是否与客户端访问地址一致。
- 检查账号状态是否为 `active`。
- 检查 OAuth 客户端是否使用了正确的 `client_id` 和 PKCE `code_verifier`。

### 注册后无法登录

检查注册审批设置。若 `registration_require_approval=true`，管理员需要在 `/admin` 将账号状态改为 `active`。

## 10. 本地开发

```bash
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest
abm-server
```

默认服务地址为 `http://127.0.0.1:18050`。本地 OAuth issuer 默认使用 `ABM_PUBLIC_BASE_URL`，未设置时回退到 `http://127.0.0.1:<port>`。生产环境请显式设置 HTTPS 地址。
