import { initPageLanguage } from "./i18n.js";

const translations = {
  en: {
    "page.title": "ABM Server MCP Guide",
    "nav.home": "Home",
    "nav.quickstart": "Quickstart",
    "nav.tools": "Tools",
    "nav.console": "Console",
    "guide.eyebrow": "AGENT MANUAL",
    "guide.title": "ABM Server MCP Guide",
    "guide.lead":
      "A complete integration guide for agents and MCP client maintainers. ABM connects a user's own Chrome browser to MCP; browser actions run locally in the extension while the server handles authentication, routing, and audit.",
    "meta.protocol": "Protocol: Streamable HTTP",
    "meta.auth": "Authentication: OAuth 2.1",
    "meta.endpoint": "Endpoint: <code>{issuer}/mcp</code>",
    "quickstart.title": "1. Quickstart",
    "quickstart.install.title": "1.1 Install the Chrome extension",
    "quickstart.install.body":
      'The ABM extension is not yet on the Chrome Web Store. Download the latest ZIP from <a href="{releaseUrl}" target="_blank" rel="noreferrer">GitHub Releases</a>, unzip it, enable Developer mode at <code>chrome://extensions</code>, then click &quot;Load unpacked&quot; and select the extracted folder.',
    "quickstart.register.title": "1.2 Create an account",
    "quickstart.register.body":
      "Register through the website, or call the public MCP endpoint with the <code>account_register</code> tool:",
    "quickstart.register.note":
      "The public endpoint exposes only <code>account_register</code>. If registration approval is enabled, new accounts are <code>pending</code> and must be approved by an administrator in the console.",
    "quickstart.connect.title": "1.3 Connect the browser extension",
    "quickstart.connect.step1":
      'Sign in to the <a href="/console">console</a>.',
    "quickstart.connect.step2":
      "Create an API Key. The plaintext is shown only once, so save it immediately.",
    "quickstart.connect.step3":
      "Open the extension options page, enter the server URL (for example <code>{issuer}</code>) and the API Key.",
    "quickstart.connect.step4":
      "Click Connect and confirm the extension is online. OAuth-authenticated browser tools acquire an exclusive connection through a browserSessionId.",
    "auth.title": "2. Authentication",
    "auth.oauth.title": "2.1 OAuth 2.1 (recommended)",
    "auth.oauth.body":
      "When an MCP client connects to <code>{issuer}/mcp</code>, it receives <code>401</code> and <code>WWW-Authenticate</code>. The client should read the protected-resource metadata, discover the authorization server, and complete dynamic client registration, the PKCE authorization-code flow, and token exchange.",
    "auth.metadata.protected": "Protected Resource Metadata",
    "auth.metadata.server": "Authorization Server Metadata",
    "auth.metadata.scopes": "Scopes",
    "auth.scope.browser": "Run browser tools through the extension",
    "auth.scope.read": "Read account, plan, and API key metadata",
    "auth.scope.write": "Create/revoke API keys and update account settings",
    "auth.oauth.note":
      "The authorization flow opens the ABM sign-in page. After sign-in, a consent page shows the client name, scopes, and the browser connections this client may use. Browser tools acquire an exclusive connection through a server-issued browserSessionId; a connection already held by another task returns ABM_CONNECTION_BUSY.",
    "auth.failure.title": "2.2 Authentication failures",
    "auth.failure.body":
      "Authentication failures return <code>401</code> with the following response header:",
    "clients.title": "3. MCP client configuration",
    "clients.http.title": "3.1 Generic HTTP configuration",
    "tools.title": "4. Tool catalog",
    "tools.browser.title": "4.1 Browser tools",
    "tools.browser.body":
      "All browser tools use the <code>browser_*</code> naming convention. They require the <code>browser</code> scope and an online extension connection.",
    "tool.browser_inject_script": "Run a script in the page's main world",
    "tool.browser_read_page_data": "Read data from a dotted window path",
    "tool.browser_navigate": "Navigate and reuse tabs",
    "tool.browser_control": "Query, update, activate, or close tabs",
    "tool.browser_extract_data": "Extract element, window, or document data",
    "tool.browser_click": "Click an element",
    "tool.browser_fill": "Fill an input or editable element",
    "tool.browser_keyboard": "Send keyboard input",
    "tool.browser_upload_file": "Inject a single base64 file",
    "tool.browser_set_files": "Inject multiple base64 files",
    "tool.browser_set_files_from_urls": "Download and inject files from URLs",
    "tool.browser_wait_elements": "Wait for elements to reach a specified count",
    "tool.browser_set_video_to_page": "Inject a staged video",
    "tool.browser_download_video_from_url":
      "Download a video to extension staging",
    "tool.browser_network_intercept": "Capture network requests through CDP",
    "tool.browser_mouse_click": "Perform a CDP mouse click",
    "tool.browser_mouse_scroll": "Perform a CDP mouse-wheel scroll",
    "tool.browser_input_sequence": "Replay a CDP input event sequence",
    "tool.browser_set_files_native": "Inject files from local absolute paths",
    "tool.browser_stage_video": "Stage and deliver a video",
    "tool.browser_send_notice": "Push an extension notification",
    "tool.browser_open_session": "Open a browser task session",
    "tool.browser_close_session": "Close a browser task session",
    "tools.account.title": "4.2 Account tools",
    "tool.account_register": "Submit a registration request (public tool)",
    "tool.account_me": "Read the current account and connection status",
    "tool.account_update_profile": "Update the display name",
    "tool.account_change_password":
      "Change the password and revoke other credentials",
    "tool.api_key_list": "List API Keys",
    "tool.api_key_create": "Create an API Key (one-time plaintext)",
    "tool.api_key_revoke": "Revoke an API Key",
    "tools.admin.title": "4.3 Administrator tools",
    "tools.admin.body":
      "Visible only to administrator accounts; the role is checked again on every call.",
    "tool.admin_list_users": "Filter accounts",
    "tool.admin_update_user": "Update status, plan, or notes",
    "tool.admin_get_settings": "Read system settings",
    "tool.admin_update_settings": "Update registration approval",
    "tool.admin_list_audit": "Read audit events",
    "examples.title": "5. Examples",
    "examples.account.title": "5.1 Read account information",
    "examples.key.title": "5.2 Create an API Key",
    "examples.key.name": "Agent browser",
    "examples.key.note":
      "The <code>plaintext</code> field in the response is shown only once; write it to the extension or a secret manager immediately.",
    "examples.browser.title": "5.3 Browser actions",
    "errors.title": "6. Errors and recovery",
    "errors.code": "Error code",
    "errors.meaning": "Meaning",
    "errors.action": "Suggested action",
    "error.ABM_INVALID_TOKEN.meaning": "Missing, invalid, or expired OAuth token",
    "error.ABM_INVALID_TOKEN.action": "Sign in and authorize again",
    "error.ABM_SCOPE_REQUIRED.meaning":
      "OAuth token is missing a required scope",
    "error.ABM_SCOPE_REQUIRED.action":
      "Re-authorize and grant the required permissions",
    "error.ABM_EXTENSION_OFFLINE.meaning": "No online extension connection",
    "error.ABM_EXTENSION_OFFLINE.action":
      "Enter the key in the extension and connect",
    "error.ABM_CONNECTION_BUSY.meaning":
      "The target browser connection is in use by another browser task",
    "error.ABM_CONNECTION_BUSY.action":
      "Wait for the other task to finish or retry later",
    "error.ABM_BROWSER_SESSION_REQUIRED.meaning":
      "A browser task handle is required",
    "error.ABM_BROWSER_SESSION_REQUIRED.action":
      "Call browser_open_session first",
    "error.ABM_BROWSER_SESSION_INVALID.meaning":
      "The browser task handle is invalid or expired",
    "error.ABM_BROWSER_SESSION_INVALID.action": "Open a new browser session",
    "error.ABM_KEY_LIMIT_REACHED.meaning":
      "API Key limit for the plan reached",
    "error.ABM_KEY_LIMIT_REACHED.action":
      "Revoke an old key or upgrade the plan",
    "error.ABM_ACCOUNT_PENDING.meaning": "Account is awaiting approval",
    "error.ABM_ACCOUNT_PENDING.action": "Wait for administrator approval",
    "error.ABM_ACCOUNT_DISABLED.meaning": "Account is disabled",
    "error.ABM_ACCOUNT_DISABLED.action": "Contact an administrator",
    "error.ABM_RATE_LIMITED.meaning": "Too many requests",
    "error.ABM_RATE_LIMITED.action": "Wait according to retryAfter",
    "security.title": "7. Security boundaries",
    "security.apiKey":
      "API Keys are stored only in extension local storage and as a server-side digest; they are never exposed to page scripts.",
    "security.oauth":
      "Dynamically registered OAuth clients use the PKCE public-client flow and are not issued a client secret.",
    "security.token":
      "OAuth tokens are stored only as SHA-256 digests and support expiry, revocation, and refresh rotation.",
    "security.browser":
      "Browser tools must run through the user's online extension; the server does not store account passwords or page cookies.",
    "security.admin":
      "Administrator actions create audit events; disabling an account revokes sessions and OAuth tokens and closes the extension connection.",
    "security.https":
      "Production deployments must use HTTPS and set <code>ABM_PUBLIC_BASE_URL</code> or <code>ABM_OAUTH_ISSUER_URL</code>.",
    "troubleshooting.title": "8. Troubleshooting",
    "troubleshooting.login.title":
      "MCP client does not open the sign-in page",
    "troubleshooting.login.body":
      "Check that the client supports OAuth and Streamable HTTP, and confirm that <code>/mcp</code> returns <code>401</code> with <code>WWW-Authenticate</code>.",
    "troubleshooting.offline.title":
      "Browser tools report that the extension is offline",
    "troubleshooting.offline.body":
      "OAuth sign-in only authenticates the MCP connection; browser tools still require an online extension. Create an API Key in the console and connect from the extension, or verify that an online connection already exists.",
    "troubleshooting.token.title":
      "Token is still invalid after authorization",
    "troubleshooting.token.body":
      "Check the server clock, confirm that <code>ABM_OAUTH_ISSUER_URL</code> matches the URL used by the client, and verify that the account status is <code>active</code>.",
  },
  zh: {
    "page.title": "ABM Server MCP 安装使用手册",
    "nav.home": "首页",
    "nav.quickstart": "快速开始",
    "nav.tools": "工具",
    "nav.console": "控制台",
    "guide.eyebrow": "AGENT 手册",
    "guide.title": "ABM Server MCP 安装使用手册",
    "guide.lead":
      "面向 Agent 和 MCP 客户端维护者的完整接入说明。ABM 把用户自己的 Chrome 浏览器接入 MCP，浏览器操作由扩展在本机执行，服务端负责鉴权、路由和审计。",
    "meta.protocol": "协议：Streamable HTTP",
    "meta.auth": "认证：OAuth 2.1",
    "meta.endpoint": "端点：<code>{issuer}/mcp</code>",
    "quickstart.title": "1. 快速开始",
    "quickstart.install.title": "1.1 安装 Chrome 扩展",
    "quickstart.install.body":
      'ABM 扩展尚未上架 Chrome Web Store。请从 <a href="{releaseUrl}" target="_blank" rel="noreferrer">GitHub Releases</a> 下载最新 ZIP，解压后在 <code>chrome://extensions</code> 开启“开发者模式”，点击“加载已解压的扩展程序”并选择解压目录。',
    "quickstart.register.title": "1.2 注册账号",
    "quickstart.register.body":
      "可以通过网页注册，也可以通过公共 MCP 端点调用 <code>account_register</code> 工具：",
    "quickstart.register.note":
      "公共端点只暴露 <code>account_register</code>。若开启了注册审批，新账号状态为 <code>pending</code>，需要管理员在控制台审批。",
    "quickstart.connect.title": "1.3 连接浏览器扩展",
    "quickstart.connect.step1":
      '登录 <a href="/console">控制台</a>。',
    "quickstart.connect.step2":
      "创建 API Key。明文只显示一次，请立即保存。",
    "quickstart.connect.step3":
      "打开扩展选项页，填写服务器地址（例如 <code>{issuer}</code>）和 API Key。",
    "quickstart.connect.step4":
      "点击连接，确认扩展在线。OAuth 认证的浏览器工具通过 browserSessionId 独占一个连接。",
    "auth.title": "2. 认证",
    "auth.oauth.title": "2.1 OAuth 2.1（推荐）",
    "auth.oauth.body":
      "MCP 客户端连接 <code>{issuer}/mcp</code> 时会收到 <code>401</code> 和 <code>WWW-Authenticate</code>。客户端应读取受保护资源元数据，发现授权服务器，完成动态客户端注册、PKCE 授权码流程和令牌交换。",
    "auth.metadata.protected": "受保护资源元数据",
    "auth.metadata.server": "授权服务器元数据",
    "auth.metadata.scopes": "Scopes",
    "auth.scope.browser": "通过浏览器扩展执行浏览器工具",
    "auth.scope.read": "读取账号、套餐和 API Key 元数据",
    "auth.scope.write": "创建/吊销 API Key、修改账号设置",
    "auth.oauth.note":
      "授权过程中会打开 ABM 登录页。登录后显示同意页，确认客户端名称、scopes 和可使用的浏览器连接。浏览器工具通过服务端生成的 browserSessionId 独占一个连接；连接已被其他任务占用时返回 ABM_CONNECTION_BUSY。",
    "auth.failure.title": "2.2 认证失败",
    "auth.failure.body":
      "认证失败返回 <code>401</code>，响应头包含：",
    "clients.title": "3. MCP 客户端配置",
    "clients.http.title": "3.1 通用 HTTP 配置",
    "tools.title": "4. 工具目录",
    "tools.browser.title": "4.1 浏览器工具",
    "tools.browser.body":
      "全部使用 <code>browser_*</code> 命名，需要 <code>browser</code> scope 和在线扩展连接。",
    "tool.browser_inject_script": "在页面主环境执行脚本",
    "tool.browser_read_page_data": "读取 window 点分路径数据",
    "tool.browser_navigate": "导航并复用标签",
    "tool.browser_control": "查询、更新、激活或关闭标签",
    "tool.browser_extract_data": "提取元素、window 或 document 数据",
    "tool.browser_click": "点击元素",
    "tool.browser_fill": "填写输入框或可编辑元素",
    "tool.browser_keyboard": "发送键盘输入",
    "tool.browser_upload_file": "注入单个 base64 文件",
    "tool.browser_set_files": "注入多个 base64 文件",
    "tool.browser_set_files_from_urls": "下载并注入 URL 文件",
    "tool.browser_wait_elements": "等待元素达到指定数量",
    "tool.browser_set_video_to_page": "注入暂存视频",
    "tool.browser_download_video_from_url": "下载视频到扩展暂存区",
    "tool.browser_network_intercept": "通过 CDP 抓取网络请求",
    "tool.browser_mouse_click": "执行 CDP 鼠标点击",
    "tool.browser_mouse_scroll": "执行 CDP 滚轮滚动",
    "tool.browser_input_sequence": "回放 CDP 输入事件序列",
    "tool.browser_set_files_native": "注入本地绝对路径文件",
    "tool.browser_stage_video": "暂存并投递视频",
    "tool.browser_send_notice": "推送扩展通知",
    "tool.browser_open_session": "打开浏览器任务会话",
    "tool.browser_close_session": "关闭浏览器任务会话",
    "tools.account.title": "4.2 账号工具",
    "tool.account_register": "注册申请（公共工具）",
    "tool.account_me": "读取当前账号和连接状态",
    "tool.account_update_profile": "修改显示名称",
    "tool.account_change_password": "修改密码并吊销其他凭证",
    "tool.api_key_list": "列出 API Key",
    "tool.api_key_create": "创建 API Key（一次性明文）",
    "tool.api_key_revoke": "吊销 API Key",
    "tools.admin.title": "4.3 管理员工具",
    "tools.admin.body": "仅管理员账号可见，并在调用时再次校验角色。",
    "tool.admin_list_users": "筛选账号",
    "tool.admin_update_user": "修改状态/套餐/备注",
    "tool.admin_get_settings": "读取系统设置",
    "tool.admin_update_settings": "修改注册审批",
    "tool.admin_list_audit": "读取审计事件",
    "examples.title": "5. 调用示例",
    "examples.account.title": "5.1 读取账号",
    "examples.key.title": "5.2 创建 API Key",
    "examples.key.name": "Agent 工作浏览器",
    "examples.key.note":
      "返回中的 <code>plaintext</code> 只出现一次，立即写入扩展或密钥管理器。",
    "examples.browser.title": "5.3 浏览器操作",
    "errors.title": "6. 错误与恢复",
    "errors.code": "错误码",
    "errors.meaning": "含义",
    "errors.action": "建议动作",
    "error.ABM_INVALID_TOKEN.meaning": "缺少、无效或过期的 OAuth 令牌",
    "error.ABM_INVALID_TOKEN.action": "重新登录授权",
    "error.ABM_SCOPE_REQUIRED.meaning": "OAuth 授权缺少 scope",
    "error.ABM_SCOPE_REQUIRED.action": "重新授权并勾选权限",
    "error.ABM_EXTENSION_OFFLINE.meaning": "没有在线扩展连接",
    "error.ABM_EXTENSION_OFFLINE.action": "在扩展中填写 Key 并连接",
    "error.ABM_CONNECTION_BUSY.meaning": "目标连接已被其他浏览器任务占用",
    "error.ABM_CONNECTION_BUSY.action": "等待其他任务结束或稍后重试",
    "error.ABM_BROWSER_SESSION_REQUIRED.meaning": "需要显式浏览器任务句柄",
    "error.ABM_BROWSER_SESSION_REQUIRED.action": "先调用 browser_open_session",
    "error.ABM_BROWSER_SESSION_INVALID.meaning": "浏览器任务句柄无效或已过期",
    "error.ABM_BROWSER_SESSION_INVALID.action": "重新打开浏览器会话",
    "error.ABM_KEY_LIMIT_REACHED.meaning": "API Key 数量达到套餐上限",
    "error.ABM_KEY_LIMIT_REACHED.action": "吊销旧 Key 或升级套餐",
    "error.ABM_ACCOUNT_PENDING.meaning": "账号等待审批",
    "error.ABM_ACCOUNT_PENDING.action": "等待管理员审批",
    "error.ABM_ACCOUNT_DISABLED.meaning": "账号已停用",
    "error.ABM_ACCOUNT_DISABLED.action": "联系管理员",
    "error.ABM_RATE_LIMITED.meaning": "请求过于频繁",
    "error.ABM_RATE_LIMITED.action": "按 retryAfter 等待",
    "security.title": "7. 安全边界",
    "security.apiKey":
      "API Key 只保存在扩展本地存储和服务端摘要中，不暴露给页面脚本。",
    "security.oauth":
      "OAuth 动态注册客户端使用 PKCE public client，不签发 client secret。",
    "security.token":
      "OAuth 令牌只保存 SHA-256 摘要，支持过期、吊销和刷新轮换。",
    "security.browser":
      "浏览器工具必须通过用户在线扩展执行；服务端不保存账号密码或页面 Cookie。",
    "security.admin":
      "管理员操作记录审计事件；账号停用会吊销会话、OAuth 令牌并关闭扩展连接。",
    "security.https":
      "生产环境必须使用 HTTPS，并设置 <code>ABM_PUBLIC_BASE_URL</code> 或 <code>ABM_OAUTH_ISSUER_URL</code>。",
    "troubleshooting.title": "8. 排查",
    "troubleshooting.login.title": "MCP 客户端没有弹出登录页",
    "troubleshooting.login.body":
      "检查客户端是否支持 OAuth 和 Streamable HTTP，并确认 <code>/mcp</code> 返回 401 与 <code>WWW-Authenticate</code>。",
    "troubleshooting.offline.title": "浏览器工具返回扩展离线",
    "troubleshooting.offline.body":
      "OAuth 登录只解决 MCP 认证，浏览器工具仍需要扩展在线。请在控制台创建 API Key，在扩展中连接，或确认已有在线连接。",
    "troubleshooting.token.title": "授权后令牌仍无效",
    "troubleshooting.token.body":
      "检查服务器时间、<code>ABM_OAUTH_ISSUER_URL</code> 是否与客户端访问地址一致，以及账号状态是否为 <code>active</code>。",
  },
};

initPageLanguage({
  translations,
  legacyStorageKeys: ["abm.landing.lang"],
});
