# ABM Server 使用场景示例
> 范围：开源单用户版 core。托管版的多用户、套餐、审批、计费不在本仓库。

> 本文给出可直接照做的端到端场景。工具名、参数和错误码以 [architecture.md](architecture.md) 为准；链路细节见 [data-flow.md](data-flow.md)。

## 0. 约定

- 示例域名：`https://abm.example.com`，请替换为你的部署地址。
- `curl` 示例假设你已经保存了 Cookie 和 CSRF。
- MCP 调用用工具名 + 参数表示，不绑定具体客户端。
- 除 `browser_open_session` / `browser_close_session` 外，浏览器工具都可带 `browserSessionId`。
- `pinned` OAuth 可以不带 `browserSessionId`；`pool` / `auto` 在多连接时必须先创建。

## 1. 首次部署与管理员引导

**目标**：空库启动，创建首个管理员，确认健康状态。

```bash
export ABM_DATABASE_URL="sqlite+aiosqlite:////data/abm.db"
export ABM_PUBLIC_BASE_URL="https://abm.example.com"
export ABM_BOOTSTRAP_ADMIN_EMAIL="admin@example.com"
export ABM_BOOTSTRAP_ADMIN_PASSWORD="change-me-please"
export ABM_SESSION_COOKIE_SECURE="true"

abm-server-migrate
abm-server
```

验证：

```bash
curl -fsS https://abm.example.com/healthz
curl -fsS https://abm.example.com/readyz
```

预期：

```json
{"ok":true,"service":"abm-browser-mcp","version":"0.1.0"}
```

首个管理员只在数据库没有管理员时创建；之后修改引导变量不会重置密码。生产环境应立即登录并修改初始密码。

## 2. 用户注册、管理员审批、登录

### 2.1 用户提交申请

```bash
curl -X POST https://abm.example.com/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "ada@example.com",
    "password": "a-long-password",
    "display_name": "Ada",
    "application_note": "用浏览器做资料整理"
  }'
```

响应为 `202` 通用接受结果，不暴露邮箱是否已存在。

### 2.2 管理员审批

在 `/admin` 选择用户，点击“批准”；或：

```bash
curl -X PATCH https://abm.example.com/api/v1/admin/users/<user-id> \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" \
  -b cookies.txt \
  -d '{"status":"active","reason":"审核通过"}'
```

### 2.3 登录

```bash
curl -c cookies.txt -X POST https://abm.example.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"a-long-password"}'
```

响应包含用户信息和 `csrfToken`，同时设置 `abm_session` 和 `abm_csrf` Cookie。

后续写请求：

```bash
CSRF=$(awk '$6=="abm_csrf" {print $7}' cookies.txt)
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" ...
```

### 2.4 使用 Google 一键登录

前提：服务端已配置 `ABM_SOCIAL_GOOGLE_CLIENT_ID` 和 `ABM_SOCIAL_GOOGLE_CLIENT_SECRET`，并且 Google OAuth 客户端登记了回调地址：

```text
https://abm.example.com/api/v1/auth/social/google/callback
```

操作：

1. 打开 `/login` 或 `/register`。
2. 点击“使用 Google 登录”。
3. 在 Google 页面选择账号并授权。
4. 首次使用时，系统按已验证邮箱自动创建 ABM 账号：
   - 如果 `ABM_REGISTRATION_REQUIRE_APPROVAL=false`，直接登录并进入控制台。
   - 如果为 `true`，账号进入待审批状态，页面提示等待管理员审批。
5. 已有同邮箱且邮箱已验证的账号会自动绑定 Google 身份。
6. 如果同邮箱账号尚未验证邮箱，系统拒绝自动绑定，提示先用密码登录后在“账号 → 登录方式”中绑定。

绑定或解绑：

```text
控制台 → 账号 → 登录方式
```

解绑需要当前登录会话；解绑后仍可使用密码或其他已绑定方式登录。自动注册账号可以使用“忘记密码”设置密码。

### 2.5 使用微信 / QQ 登录

前提：已配置 `ABM_SOCIAL_WECHAT_CLIENT_ID` / `ABM_SOCIAL_WECHAT_CLIENT_SECRET` 或 `ABM_SOCIAL_QQ_CLIENT_ID` / `ABM_SOCIAL_QQ_CLIENT_SECRET`，并在对应开放平台登记回调域名：

```text
https://abm.example.com/api/v1/auth/social/wechat/callback
https://abm.example.com/api/v1/auth/social/qq/callback
```

微信和 QQ 不返回邮箱地址，首次登录会多一步：

1. 打开 `/login` 或 `/register`。
2. 点击“使用微信登录”或“使用 QQ 登录”。
3. 扫码或跳转授权。
4. 首次使用时进入 `/social/complete`，填写邮箱和显示名称。
5. 提交后：
   - 邮箱未被占用：创建账号，发送验证邮件；审批关闭时直接进入控制台，审批开启时进入待审批。
   - 邮箱已被占用：拒绝自动绑定，提示先用密码登录，再到“控制台 → 账号 → 登录方式”绑定。
6. 再次使用微信/QQ 登录时，已有身份会直接登录。

注意：

- 微信/QQ 需要已备案的公开域名，不能使用 `localhost`。
- 补充邮箱创建的账号初始为未验证邮箱，可先使用社交登录，后续在控制台验证邮箱。
- 微信/QQ 绑定到当前已登录账号时不要求 provider 返回邮箱。

## 3. 创建 API Key 并连接扩展

### 3.1 创建 Key

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  -X POST https://abm.example.com/api/v1/api-keys \
  -H 'Content-Type: application/json' \
  -d '{"name":"办公浏览器"}'
```

响应：

```json
{
  "id": "uuid",
  "name": "办公浏览器",
  "prefix": "abm_a1b2c3d4e5f6",
  "plaintext": "abm_a1b2c3d4e5f6_<secret>",
  "status": "active",
  "createdAt": "2026-10-26T00:00:00Z"
}
```

`plaintext` 只出现一次，立即保存。

### 3.2 扩展连接

1. 打开扩展 popup。
2. 服务器地址填 `https://abm.example.com`。
3. API Key 粘贴完整 `abm_...`。
4. 点击“连接”。

预期：状态变为“已连接”，服务端 `/api/v1/session/status` 能看到扩展 ID 和版本。

### 3.3 验证运行状态

```bash
curl -H "Authorization: Bearer abm_a1b2c3d4e5f6_<secret>" \
  https://abm.example.com/api/v1/session/status
```

返回账号、Key 前缀、连接信息和 pending 数量。

## 4. MCP 客户端 OAuth：固定一个浏览器

客户端配置：

```json
{
  "mcpServers": {
    "abm": {
      "type": "http",
      "url": "https://abm.example.com/mcp"
    }
  }
}
```

流程：

1. 客户端连接 `/mcp`，收到 `401` 和受保护资源元数据。
2. 客户端读取元数据，完成 DCR、PKCE 和浏览器登录。
3. 同意页选择“固定一个浏览器”，选中目标 API Key。
4. 客户端换取 token，开始调用工具。

示例：

```json
{"name":"account_me","arguments":{}}
```

返回账号、套餐、有效 Key 数量和扩展在线状态。

## 5. MCP 客户端 OAuth：多个浏览器与并行任务

同意页选择“指定多个浏览器”，勾选两个以上连接。

### 5.1 创建任务句柄

```json
{"name":"browser_open_session","arguments":{}}
```

响应：

```json
{
  "browserSessionId": "bs_xxx",
  "connectionId": "api-key-uuid"
}
```

也可以指定池内连接：

```json
{"name":"browser_open_session","arguments":{"connectionId":"api-key-uuid"}}
```

### 5.2 使用句柄

```json
{"name":"browser_navigate","arguments":{
  "url":"https://example.com",
  "browserSessionId":"bs_xxx"
}}
```

### 5.3 释放

```json
{"name":"browser_close_session","arguments":{"browserSessionId":"bs_xxx"}}
```

注意：

- 同一连接同一时间只能被一个 `browserSessionId` 占用。
- 连接被占用返回 `ABM_CONNECTION_BUSY`。
- 句柄 TTL 默认 30 分钟，每次工具调用续租。
- 连接断开或 TTL 到期自动释放。

## 6. 浏览器自动化：导航、点击、填表、提取

### 6.1 导航并复用标签

```json
{"name":"browser_navigate","arguments":{
  "url":"https://example.com/login",
  "waitUntil":"load",
  "reuse":"site",
  "browserSessionId":"bs_xxx"
}}
```

返回：

```json
{
  "success": true,
  "url": "https://example.com/login",
  "tabId": 123,
  "reused": true,
  "reuseMode": "site"
}
```

只复用 `abm:browser` 分组内的标签，不接管用户私人标签。

### 6.2 等待元素并填表

```json
{"name":"browser_wait_elements","arguments":{
  "selector":"#email",
  "count":1,
  "timeout":10000,
  "browserSessionId":"bs_xxx"
}}
```

```json
{"name":"browser_fill","arguments":{
  "selector":"#email",
  "value":"ada@example.com",
  "clearBefore":true,
  "browserSessionId":"bs_xxx"
}}
```

```json
{"name":"browser_fill","arguments":{
  "selector":"#password",
  "value":"secret",
  "browserSessionId":"bs_xxx"
}}
```

### 6.3 点击并等待跳转

```json
{"name":"browser_click","arguments":{
  "selector":"button[type=submit]",
  "waitClickable":true,
  "browserSessionId":"bs_xxx"
}}
```

点击后如需严格等待导航，客户端可以再调用 `browser_wait_elements` 或 `browser_extract_data` 轮询目标页面。

### 6.4 提取数据

```json
{"name":"browser_extract_data","arguments":{
  "selector":".result-row",
  "source":"element",
  "attribute":"textContent",
  "all":true,
  "browserSessionId":"bs_xxx"
}}
```

读取页面全局变量：

```json
{"name":"browser_read_page_data","arguments":{
  "path":"__NEXT_DATA__.props.pageProps",
  "browserSessionId":"bs_xxx"
}}
```

## 7. 标签工作区：reuseKey

同一站点需要两个互不干扰的标签：

```json
{"name":"browser_navigate","arguments":{
  "url":"https://example.com/search?q=A",
  "reuseKey":"search-A",
  "browserSessionId":"bs_xxx"
}}
```

```json
{"name":"browser_navigate","arguments":{
  "url":"https://example.com/search?q=B",
  "reuseKey":"search-B",
  "browserSessionId":"bs_xxx"
}}
```

两个 `reuseKey` 会落到两个不同的标签。标签被关闭后，下次按站点规则兜底重建。`reuseKey` 记录最多保留 50 个。

## 8. 文件上传

### 8.1 单文件 Base64

```json
{"name":"browser_upload_file","arguments":{
  "selector":"input[type=file]",
  "base64Data":"<base64>",
  "fileName":"report.pdf",
  "mimeType":"application/pdf",
  "browserSessionId":"bs_xxx"
}}
```

### 8.2 多文件 Base64

```json
{"name":"browser_set_files","arguments":{
  "selector":"input[type=file]",
  "files":[
    {"base64Data":"<base64>","fileName":"a.png","mimeType":"image/png"},
    {"base64Data":"<base64>","fileName":"b.png","mimeType":"image/png"}
  ],
  "browserSessionId":"bs_xxx"
}}
```

### 8.3 URL 文件

```json
{"name":"browser_set_files_from_urls","arguments":{
  "selector":"input[type=file]",
  "urls":[
    {"url":"https://example.com/a.png","fileName":"a.png"},
    {"url":"https://example.com/b.png","fileName":"b.png"}
  ],
  "browserSessionId":"bs_xxx"
}}
```

扩展需要目标域名的 host 权限；没有权限时返回 `needPermission`，在 popup 中授权后重试。

### 8.4 本机绝对路径（CDP）

```json
{"name":"browser_set_files_native","arguments":{
  "selector":"input[type=file]",
  "paths":["/Users/ada/Documents/report.pdf"],
  "browserSessionId":"bs_xxx"
}}
```

只能注入扩展所在机器上可访问的路径。

## 9. 网络请求检查

```json
{"name":"browser_network_intercept","arguments":{
  "cmd":"start",
  "tabId":123,
  "browserSessionId":"bs_xxx"
}}
```

```json
{"name":"browser_network_intercept","arguments":{
  "cmd":"list",
  "filter":"/api/",
  "browserSessionId":"bs_xxx"
}}
```

```json
{"name":"browser_network_intercept","arguments":{
  "cmd":"detail",
  "requestId":"12345.67",
  "compress":true,
  "browserSessionId":"bs_xxx"
}}
```

```json
{"name":"browser_network_intercept","arguments":{
  "cmd":"stop",
  "browserSessionId":"bs_xxx"
}}
```

抓包数据只在扩展 service worker 生命周期内有效；大响应默认 gzip + base64。

## 10. 视频投递

### 10.1 Bridge 模式

1. 扩展保持在线。
2. 打开 `/video-bridge` 页面。
3. 调用：

```json
{"name":"browser_stage_video","arguments":{
  "fileName":"demo.mp4",
  "fileType":"video/mp4",
  "url":"https://example.com/demo.mp4",
  "delivery":"bridge",
  "browserSessionId":"bs_xxx"
}}
```

4. 服务端把源流式写入临时文件，桥页面拉取分片并推送给扩展。
5. 调用：

```json
{"name":"browser_set_video_to_page","arguments":{
  "selector":"input[type=file]",
  "clearAfterSet":true,
  "browserSessionId":"bs_xxx"
}}
```

### 10.2 URL 模式

```json
{"name":"browser_stage_video","arguments":{
  "fileName":"demo.mp4",
  "url":"https://example.com/demo.mp4",
  "delivery":"url",
  "browserSessionId":"bs_xxx"
}}
```

URL 源由扩展直接下载，服务端不接触视频字节。需要扩展对视频域名有权限；权限不足返回 `ABM_VIDEO_PERMISSION_REQUIRED`。

base64 源会先写入服务端临时文件，再生成一次性下载地址给扩展，交付后删除。

### 10.3 Auto

`delivery` 省略或设为 `auto`：

- URL 源 → 扩展直接下载原始地址。
- base64 源 + 扩展在线 → 一次性地址。
- base64 源 + 扩展离线 → bridge。
- 权限不足不会静默回退到服务器中转。

本机大文件优先使用 `browser_set_files_native`，只传本机绝对路径，视频字节不经过服务端。

视频暂存在扩展内存，30 分钟内有效；service worker 回收后丢失，需要重新投递。服务端临时文件在交付、失败或 TTL 到期后删除，不做持久化存储。

## 11. 通知

```json
{"name":"browser_send_notice","arguments":{
  "title":"任务完成",
  "level":"info",
  "body":"搜索结果已整理完毕。",
  "actionUrl":"https://example.com/results",
  "browserSessionId":"bs_xxx"
}}
```

扩展保存通知、显示未读角标；popup 最多保留 20 条。`actionUrl` 只允许 http/https。

## 12. 吊销、停用与密码修改

### 12.1 吊销单把 Key

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  -X DELETE https://abm.example.com/api/v1/api-keys/<key-id>
```

效果：

- Key 立即无法鉴权。
- 使用该 Key 的扩展连接被关闭。
- 该 Key 的视频作业不再可用。

### 12.2 停用账号

管理员在 `/admin` 将状态改为 `disabled`，或：

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  -X PATCH https://abm.example.com/api/v1/admin/users/<user-id> \
  -H 'Content-Type: application/json' \
  -d '{"status":"disabled","reason":"违规使用"}'
```

效果：账号会话后续请求被拒绝、OAuth token 全部吊销、扩展连接全部关闭。

### 12.3 修改密码

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  -X PATCH https://abm.example.com/api/v1/auth/password \
  -H 'Content-Type: application/json' \
  -d '{"current_password":"old","new_password":"a-new-long-password"}'
```

其他账号会话被吊销，当前会话保留。Web 改密不会主动吊销 OAuth token；通过 MCP `account_change_password` 改密会同时吊销除当前 access token 外的其他 OAuth token。

## 13. 管理员操作

| 操作 | 页面 | HTTP |
|---|---|---|
| 查看用户 | `/admin` | `GET /api/v1/admin/users?status=pending` |
| 批准/拒绝/停用/启用 | `/admin` | `PATCH /api/v1/admin/users/{id}` |
| 修改套餐/到期时间 | `/admin` | `PATCH /api/v1/admin/users/{id}` |
| 注册审批开关 | `/admin` | `PATCH /api/v1/admin/settings` |
| 查看审计 | `/admin` | `GET /api/v1/admin/audit?limit=50` |

MCP 管理员工具：

```json
{"name":"admin_list_users","arguments":{"status":"pending","limit":50}}
{"name":"admin_update_user","arguments":{"userId":"uuid","status":"active"}}
{"name":"admin_get_settings","arguments":{}}
{"name":"admin_update_settings","arguments":{"registrationRequireApproval":true}}
{"name":"admin_list_audit","arguments":{"limit":50}}
```

## 14. 公共 MCP 注册（Agent）

`/mcp/public` 不需要认证，只暴露 `account_register`：

```json
{"name":"account_register","arguments":{
  "email":"agent-user@example.com",
  "password":"a-long-password",
  "displayName":"Agent User",
  "applicationNote":"由 Agent 自动申请"
}}
```

结果不暴露邮箱是否存在；注册请求按 IP 限流。审批策略与其他注册入口一致。

## 15. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 登录 429 | 同一 IP/邮箱尝试过多 | 等待窗口结束，或调整 `ABM_LOGIN_RATE_LIMIT_*` |
| 登录 403 `ABM_ACCOUNT_PENDING` | 账号待审批 | 管理员在 `/admin` 批准 |
| MCP 401 | 无 token / token 过期 / 已吊销 | 重新 OAuth；检查 refresh |
| 工具返回 `ABM_EXTENSION_OFFLINE` | 扩展未连接或 Key 不一致 | 打开 popup 检查 Key 和连接状态 |
| 工具返回 `ABM_CONNECTION_BUSY` | 连接被其他 `browserSessionId` 占用 | 等待或改用池内其他连接 |
| 工具返回 `ABM_BROWSER_SESSION_REQUIRED` | pool/auto 未创建句柄 | 先 `browser_open_session` |
| 工具返回 `ABM_BROWSER_SESSION_INVALID` | 句柄过期/连接断开 | 重新 `browser_open_session` |
| 上传返回 `needPermission` | 扩展没有目标域名权限 | 在 popup 权限页添加域名 |
| 视频 URL 模式失败 | 扩展无权限/源站不可达 | 授权域名或改用 bridge |
| 视频 `ABM_VIDEO_PERMISSION_REQUIRED` | 扩展缺少视频域名权限 | 在 popup 权限页添加域名后重试 |
| 视频 `ABM_VIDEO_BUSY` | 单 Key 或服务端活跃作业达上限 | 等待现有作业结束 |
| 视频 `ABM_VIDEO_EXPIRED` | 作业已交付/过期 | 重新 `browser_stage_video` |
| 页面空白/找不到元素 | 选择器或页面状态变化 | 先 `browser_wait_elements`，再重试 |
| `/readyz` 503 | 数据库不可用 | 检查数据库连接和迁移 |

## 16. 最小验收清单

- [ ] 空库 `abm-server-migrate` 成功。
- [ ] 注册 → 审批 → 登录成功。
- [ ] 创建 Key，扩展连接成功。
- [ ] MCP OAuth pinned 可以调用 `account_me`。
- [ ] pool 模式 `browser_open_session` 成功，连接冲突返回 busy。
- [ ] 浏览器导航、点击、填表、提取成功。
- [ ] base64 / URL / 本机路径上传成功。
- [ ] bridge / url / auto 三种视频模式成功。
- [ ] 通知进入 popup，角标更新。
- [ ] 吊销 Key 后扩展断开，工具返回离线。
- [ ] 停用账号后 MCP token 失效。
- [ ] `/healthz`、`/readyz` 正常。
