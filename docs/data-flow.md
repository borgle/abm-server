# ABM Server 数据流

> 本文用端到端时序说明数据如何流动、由谁拥有、在哪里失败。公开字段和错误码见 [architecture.md](architecture.md)，实现细节见 [detailed-design.md](detailed-design.md)。

## 0. 参与方与边界

| 参与方 | 说明 |
|---|---|
| Browser | 用户浏览器中的 ABM Web 页面 |
| Web/API | FastAPI Web 路由与 `/api/v1` |
| Accounts | 账号、会话、API Key、管理员服务 |
| DB | SQLite / PostgreSQL |
| Gateway | 扩展 WebSocket 网关 |
| Extension | Chrome 扩展 service worker |
| MCP Client | 支持 Streamable HTTP + OAuth 的 MCP 客户端 |
| MCP | `/mcp` / `/mcp/public` |
| OAuth | 授权服务器与同意页 |
| Video | 视频作业协调器 |
| Bridge | `/video-bridge` 桥页面 |

信任边界：

- **账号边界**：Cookie 会话 + CSRF。
- **MCP 边界**：OAuth access token + scope + 连接策略。
- **扩展边界**：API Key + 单一活动 WebSocket。
- **页面边界**：扩展注入脚本只能访问被授权的标签页。

## 1. 注册与审批

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant W as Web /register
    participant A as Accounts
    participant D as DB
    participant AD as 管理员 /admin
    U->>W: 提交邮箱、密码、显示名称、使用场景
    W->>A: POST /api/v1/auth/register
    A->>A: 规范化邮箱、校验密码长度
    A->>D: 查询邮箱是否已存在
    alt 已存在
        A-->>W: 202 通用接受结果（不暴露存在性）
    else 新账号
        A->>D: 插入 users(status=pending 或 active)
        A->>D: 写审计 ABM_ACCOUNT_REGISTERED
        A-->>W: 202 通用接受结果
    end
    W-->>U: 显示“申请已提交”
    AD->>A: PATCH /api/v1/admin/users/{id} status=active
    A->>D: 更新状态、approved_at、审计
    A-->>AD: 更新后的用户
```

要点：

- 注册响应不泄露邮箱是否存在。
- 审批策略来自 `settings.registration_require_approval`。
- 待审批、拒绝、停用账号不能登录。
- 审批和套餐修改写入审计。

## 2. 登录与会话

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant W as Web /login
    participant A as Accounts
    participant D as DB
    U->>W: 邮箱 + 密码
    W->>A: POST /api/v1/auth/login
    A->>D: 按邮箱读取用户
    A->>A: Argon2id 校验密码
    alt 凭证错误
        A-->>W: 401 ABM_INVALID_CREDENTIALS
    else 账号非 active
        A-->>W: 403 ABM_ACCOUNT_*
    else 成功
        A->>D: 创建 account_session（token/csrf 摘要）
        A-->>W: 用户信息 + csrfToken
        W-->>U: Set-Cookie abm_session + abm_csrf
        W->>U: 跳转 next 或 /console
    end
```

后续写请求：

```text
Cookie: abm_session=...
X-CSRF-Token: <abm_csrf 的值>
Origin: <同源>
```

服务端校验 CSRF 摘要和 Origin；失败返回 `ABM_CSRF_INVALID`。

### 2.1 社交登录与自动注册

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant W as Web /login
    participant S as Social routes
    participant P as Google / GitHub / Microsoft
    participant D as DB
    U->>W: 点击“使用 Google 登录”
    W->>S: GET /api/v1/auth/social/google/start
    S->>D: 保存 state 摘要 + PKCE verifier + next
    S-->>U: 303 到 provider 授权页
    U->>P: 授权
    P-->>S: GET /callback?code&state
    S->>D: 消费 state（一次性）
    S->>P: 用 code + verifier 换取 profile
    P-->>S: subject + email + email_verified
    alt 身份已绑定
        S->>D: 读取 identity + user
    else 新身份且微信/QQ 无邮箱
        S->>D: 创建 social_pending_registration
        S-->>U: /social/complete 补充邮箱
    else 新身份且邮箱已验证
        S->>D: 查询同邮箱账号
        alt 已有已验证账号
            S->>D: 创建 external_identity，绑定
        else 没有账号
            S->>D: 创建 users + external_identity
        end
    else 邮箱未验证
        S-->>U: /login?social_error=email_unverified
    end
    alt 账号 active
        S->>D: 创建 account_session
        S-->>U: Set-Cookie + 跳转 next
    else pending / rejected / disabled
        S-->>U: /login?social_error=account_*
    end
```

要点：

- 未验证邮箱不能自动注册或绑定。
- state 绑定 `abm_social_state_<provider>` HttpOnly Cookie，回调必须同时匹配 state 和 Cookie。
- 微信/QQ 不返回邮箱；首次注册跳转 `/social/complete`，补充邮箱后创建 `email_verified_at=null` 的账号并发送验证邮件。
- 补充邮箱若已属于现有账号，不自动绑定，要求密码登录后在控制台绑定。
- 同邮箱已有账号但邮箱未验证时返回 `email_conflict`，要求先密码登录再绑定。
- 审批开启时，社交自动注册只创建 `pending` 账号，不创建会话。
- 社交登录成功后的账号会话与密码登录一致；MCP OAuth 仍需单独授权。

## 3. 创建 API Key 与扩展连接

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant W as Console
    participant K as API Keys
    participant D as DB
    participant E as Extension
    participant G as Gateway
    U->>W: 输入 Key 名称并创建
    W->>K: POST /api/v1/api-keys（CSRF）
    K->>K: 用户级锁：统计有效 Key
    alt 达到套餐上限
        K-->>W: 409 ABM_KEY_LIMIT_REACHED
    else 可创建
        K->>K: 生成 abm_<prefix>_<secret>、SHA-256
        K->>D: 插入 api_keys + 审计
        K-->>W: 201 元数据 + 一次性明文
        W-->>U: 展示一次性 Key 面板
    end
    U->>E: 在 popup 填写服务器地址和 Key
    E->>E: 保存到 abm.connection
    E->>G: WSS /api/v1/extension/ws（abm.v1）
    E->>G: session.hello { apiKey, extensionId, version }
    G->>K: 解析 Key + 用户状态
    alt Key 无效/吊销/账号停用
        G-->>E: error + 关闭码 1008，停止重连
    else 有效
        G->>G: 注册 peer（同一 Key 替换旧连接）
        G-->>E: session.ready { account, apiKeyId }
    end
```

要点：

- 完整 Key 只出现一次；数据库只有摘要。
- 同一 API Key 最多一个活动扩展连接；新连接替换旧连接。
- Key 吊销会立即关闭对应连接；账号停用会关闭该用户全部连接。

## 4. 扩展 WebSocket 与工具调用

```mermaid
sequenceDiagram
    autonumber
    participant M as MCP / Admin
    participant X as MCP Service
    participant G as Gateway
    participant E as Extension
    participant T as Browser Tab
    M->>X: tools/call browser_click
    X->>X: 校验 scope、角色、参数
    X->>X: 解析 api_key_id / browserSessionId
    alt 无在线连接
        X-->>M: ABM_EXTENSION_OFFLINE
    else 连接被占用
        X-->>M: ABM_CONNECTION_BUSY
    else 可路由
        X->>G: call_tool(api_key_id, name, args)
        G->>G: 创建 pending call call_<uuid>
        G->>E: tool.invoke { id, name, arguments }
        E->>E: registry 查找工具
        E->>T: chrome.scripting / CDP / tabs API
        T-->>E: 页面结果
        E-->>G: tool.result { status, content/error }
        G->>G: 校验 id 和 api_key_id，完成 Future
        G-->>X: 结果
        X-->>M: MCP CallToolResult
    end
```

失败路径：

| 位置 | 错误 |
|---|---|
| 扩展离线 | `ABM_EXTENSION_OFFLINE` |
| 连接被其他会话占用 | `ABM_CONNECTION_BUSY` |
| 工具未注册 | `ABM_TOOL_NOT_FOUND` |
| 扩展执行异常 | `ABM_TOOL_EXECUTION_FAILED` |
| 超时 | `ABM_TOOL_TIMEOUT` |
| 结果结构不合法 | `ABM_TOOL_RESULT_INVALID` |

## 5. MCP OAuth 连接

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant M as MCP /mcp
    participant O as OAuth Service
    participant W as Web 同意页
    participant D as DB
    C->>M: POST /mcp（无 token）
    M-->>C: 401 WWW-Authenticate + resource metadata
    C->>O: GET /.well-known/oauth-protected-resource/mcp
    C->>O: GET /.well-known/oauth-authorization-server
    C->>O: POST /register（DCR）
    O->>D: 保存 public client
    C->>O: GET /authorize?client_id&PKCE&scope
    O->>D: 创建 pending authorization
    O-->>C: 302 /oauth/authorize?request_id
    C->>W: 打开同意页
    W->>D: 读取 pending + 当前账号
    W-->>C: 展示账号、scopes、连接策略
    C->>W: 批准（pinned/pool/auto）
    W->>O: approve_authorization
    O->>D: 校验连接归属、生成 code、删除 pending、写审计
    O-->>C: 302 redirect_uri?code&state
    C->>O: POST /token（code + PKCE）
    O->>D: 标记 code used，签发 access/refresh
    O-->>C: access_token + refresh_token
    C->>M: POST /mcp Authorization: Bearer access_token
    M->>D: load_access_token（摘要、过期、吊销、用户 active）
    M-->>C: 初始化成功
```

刷新与吊销：

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant O as OAuth
    participant D as DB
    C->>O: POST /token grant_type=refresh_token
    O->>D: 校验 refresh 摘要、client、过期
    O->>D: 吊销旧 refresh，签发新 access/refresh（保留连接策略）
    O-->>C: 新 token
    C->>O: POST /revoke
    O->>D: 标记 access/refresh revoked
```

## 6. 浏览器工具与 browserSessionId

### 6.1 pinned

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant M as MCP
    participant G as Gateway
    C->>M: browser_navigate（OAuth pinned，无 browserSessionId）
    M->>M: connection_mode=pinned → 固定 api_key_id
    M->>G: call_tool
    G-->>M: 结果
    M-->>C: 结果
```

### 6.2 pool / auto

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant M as MCP
    participant G as Gateway
    C->>M: browser_open_session { connectionId? }
    M->>M: 校验 pinned/pool 范围
    M->>G: acquire_connection_for_session
    G->>G: 选择未占用连接，写租约
    G-->>M: api_key_id
    M-->>C: { browserSessionId, connectionId }
    C->>M: browser_navigate { browserSessionId }
    M->>G: touch_session + 校验范围
    G-->>M: api_key_id（续租）
    M->>G: call_tool
    G-->>M: 结果
    M-->>C: 结果
    C->>M: browser_close_session { browserSessionId }
    M->>G: release_session
    M-->>C: { closed: true }
```

错误：

- `auto` / `pool` 没有 `browserSessionId` → `ABM_BROWSER_SESSION_REQUIRED`。
- `browserSessionId` 不存在、过期、连接离线 → `ABM_BROWSER_SESSION_INVALID`。
- 连接不在 OAuth 范围 → `ABM_CONNECTION_FORBIDDEN`。
- 所有连接被占用 → `ABM_CONNECTION_BUSY`。
- 无在线连接 → `ABM_EXTENSION_OFFLINE`。

## 7. 账号 / API Key / 管理员 MCP 工具

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant M as MCP
    participant S as Accounts / Keys / Admin
    participant D as DB
    C->>M: tools/call api_key_create
    M->>M: 校验 account:write
    M->>S: create_api_key(user)
    S->>D: 额度检查 + 插入 Key + 审计
    S-->>M: 元数据 + 一次性明文
    M-->>C: 结果
    C->>M: tools/call admin_update_user
    M->>M: 校验 account:write + role=admin
    M->>S: update_user(...)
    S->>D: 更新用户/套餐 + 审计
    S-->>M: 更新结果
    M-->>C: 结果
```

普通用户调用管理员工具 → `ABM_ADMIN_REQUIRED`；跨用户操作不会通过参数注入，工具始终使用当前 OAuth 用户。

## 8. 视频投递

### 8.1 bridge

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant M as MCP
    participant V as VideoService
    participant B as /video-bridge
    participant E as Extension
    C->>M: browser_stage_video { base64/url, delivery=bridge }
    M->>V: stage()
    V->>V: 流式写入临时文件、计算分片、创建 job
    V-->>M: pending
    B->>V: GET /api/v1/video/jobs?pending=1
    V-->>B: job 元数据
    B->>V: GET /chunks/{index}
    V-->>B: base64 分片
    B->>E: abm.video.begin/chunk/finish
    E->>E: 组装并写入暂存区
    E-->>B: 进度/完成
    B->>V: POST /jobs/{id}/result
    V->>V: settle delivered，删除临时文件
    V-->>M: 作业完成
    C->>M: browser_set_video_to_page { selector }
    M->>E: tool.invoke
    E->>E: 暂存区 → 页面 file input
```

### 8.2 url

```mermaid
sequenceDiagram
    autonumber
    participant M as MCP
    participant V as VideoService
    participant G as Gateway
    participant E as Extension
    participant P as 页面
    M->>V: stage(delivery=url)
    alt URL 源
        V->>V: 创建 job，保存原始 URL
    else base64 源
        V->>V: 写入临时文件 + 一次性 download_url
    end
    V->>G: call browser_download_video_from_url
    G->>E: tool.invoke
    E->>E: 检查 host 权限并下载
    E->>E: 写入暂存区
    E-->>G: fileSize
    G-->>V: 结果
    V->>V: 更新元数据、settle delivered
    V-->>M: 作业完成
    M->>E: browser_set_video_to_page
    E->>P: 注入 file input
```

### 8.3 auto

- URL 源：扩展直接下载原始地址，服务端不接触视频字节。
- base64 源 + 扩展在线：`url`（服务端临时托管）。
- base64 源 + 扩展离线：`bridge`。
- 权限不足返回 `ABM_VIDEO_PERMISSION_REQUIRED`，不静默回退到服务器中转。
- 本机大文件优先 `browser_set_files_native`，字节不经过服务端。

## 9. 通知下发

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant M as MCP
    participant G as Gateway
    participant E as Extension
    participant S as chrome.storage.local
    C->>M: browser_send_notice { title, level, body, actionUrl }
    M->>M: 校验 browser scope + 在线连接
    M->>G: send_notice(api_key_id, ...)
    G->>E: notice.push { id, title, level, body, actionUrl }
    E->>S: 保存 abm.notice:<id>（最多 20 条）
    E->>E: 刷新未读角标
    E-->>C: 结果（通过 MCP）
```

## 10. 吊销、停用与断开传播

```mermaid
sequenceDiagram
    autonumber
    participant A as Admin / User
    participant S as Service
    participant D as DB
    participant G as Gateway
    participant E as Extension
    A->>S: 吊销 Key / 停用账号 / 改密
    S->>D: 更新状态 + 吊销 token/session + 审计
    S->>G: close_for_key / close_for_user
    G->>E: error（ABM_API_KEY_REVOKED / ABM_ACCOUNT_DISABLED）
    G->>E: WebSocket close 1008
    E->>E: 停止自动重连，展示需要用户处理的提示
    S-->>A: 操作完成
```

要点：

- 吊销/停用先落库，再关闭连接；关闭失败不回滚业务状态。
- 账号停用同时吊销 OAuth token，MCP 客户端下次请求得到 401。
- Web 修改密码只吊销其他账号会话；MCP `account_change_password` 还会吊销除当前 access token 外的其他 OAuth token。

## 11. 数据所有权速查

| 数据 | 所有者 | 生命周期 |
|---|---|---|
| 用户、会话、Key、OAuth、审计 | 数据库 | 持久 |
| 扩展连接、pending 调用 | Gateway 进程内存 | 连接/调用期间 |
| 浏览器任务租约 | Gateway 进程内存 | TTL 或 close |
| 视频作业与临时文件 | VideoService 临时目录 | TTL，交付/失败后删除 |
| 视频桥分片 | 服务端临时文件 → 扩展暂存区 | 桥接期间 / 30 分钟 |
| 扩展通知 | `chrome.storage.local` | 最近 20 条 |
| 扩展配置 | `chrome.storage.local` | 持久 |
