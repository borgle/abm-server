# ABM（a browser mcp） Server

ABM 是 **a browser mcp** 的简称。本项目是一个 Python 服务，用于将 MCP 客户端安全连接到用户自己的浏览器。

主要能力：

- 用户注册申请、管理员审批和 Web 登录；支持微信、QQ、Google、GitHub、Microsoft 一键登录和自动注册（微信/QQ 首次登录补充邮箱，且遵循审批策略）。
- MCP 内置 OAuth 2.1 Authorization Code + PKCE + 动态客户端注册。
- 单账号管理多把 `abm_` API Key，并按套餐限制数量。
- 浏览器扩展 WebSocket 网关。
- 标准 MCP Streamable HTTP。
- 23 个 `browser_*` 浏览器工具、7 个账号/API Key 工具和 5 个管理员工具。
- `/mcp/public` 公开注册端点，仅暴露 `account_register`。
- 通知下发，以及 bridge、url、auto 三种视频投递模式；URL 源由扩展直连，bridge 仅使用临时文件中转，不持久化存储。
- 视频桥可从受信扩展自动获取 API Key 与扩展 ID。
- 用户与管理员 Web 管理台、Chrome 扩展 landing page 和 MCP 安装手册；控制台支持一键连接扩展、生成常见 Agent 的 MCP 配置，并展示扩展状态、工作流模板、按 Key 用量和套餐配额。
- 注册、登录、控制台、管理后台、landing page、MCP 手册、视频桥和 OAuth 授权页支持中英文切换；默认跟随客户端语言（zh / en，其他回退 en），选择保存在 `abm.lang`。
- 账号支持邮箱验证、忘记密码、登录会话管理、数据导出和密码确认后的账号删除。
- 套餐配额支持软/硬模式，硬模式下超限返回 `ABM_QUOTA_EXCEEDED`；80% / 100% 阈值可推送扩展通知、邮件和 Webhook。
- 控制台提供账号通知中心，展示配额、Key 和连接相关事件。
- MCP 工具描述、工具结果、HTTP 错误和 OAuth 错误描述使用英文规范文案；页面首屏在翻译完成前不会闪现中文模板。

## 文档

- [文档索引](docs/README.md)
- [完整架构设计](docs/architecture.md)
- [详细设计](docs/detailed-design.md)
- [数据流](docs/data-flow.md)
- [使用场景示例](docs/scenarios.md)
- [开发计划](docs/development-plan.md)
- [社交登录配置](docs/social-login.md)
- [Local mode（数据不出本机）](docs/local-mode.md)
- [Agent MCP 安装使用手册](docs/mcp-agent-guide.md)
- [创作台设计方案](docs/creation-module.md) · [交互原型](docs/prototypes/creation-studio.html)
- [控制台与管理后台重构方案](docs/console-admin-refactor.md) · [交互原型](docs/prototypes/account-admin-refactor.html)
- [开发指南](AGENTS.md)

## 规划目录

```text
abm_server/
  main.py
  config.py
  database.py
  accounts/
  admin/
  api_keys/
  audit/
  auth/
  extension_gateway/
  mcp/
  social/
  tools/
  video/
  web/
alembic/
docs/
tests/
```

## 开发

```bash
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest
abm-server
```

默认 SQLite 数据库位于 `./data/abm.db`。

## Docker 部署

```bash
cp .env.docker.example .env
docker compose up -d --build
```

首次启动会执行 Alembic，并使用管理员初始化变量创建首个管理员。数据保存在
`abm_data` volume 中。生产环境请使用 HTTPS 反向代理、设置
`ABM_PUBLIC_BASE_URL`，并保持 `ABM_SESSION_COOKIE_SECURE=true`。通过
Cloudflare Tunnel 或本机反向代理访问时，同时设置
`ABM_FORWARDED_ALLOW_IPS=*`，让 Uvicorn 正确识别 HTTPS 和外部域名。

## 创作台：图片与排版

管理后台的「套餐与模型」可以给每个套餐绑定图片模型（OpenAI Images 兼容接口），
并在「参数配置」里设置每日生图次数、单次张数和存储上限。

- 图片、封面、小红书卡片和导出 HTML 都存在对象存储里，数据库只记录 key 和校验和。
- 封面按平台裁切到精确尺寸：小红书 1080×1440、公众号 900×383、知乎 1200×675、视频号 1080×1260、主稿 1080×1080。
- 支持以已有图片为参考改图（`reference_media_id`），资产库列表显示封面缩略图。
- 选题雷达勾选多个引擎时会并行搜索，默认并发 2（`ABM_RESEARCH_PARALLEL_SEARCHES`，1 为串行）；每个引擎独立标签页，统一归到 `ABM · 检索 · 关键词` 标签组。
- 搜索或抓取遇到验证码/登录墙时任务会暂停：在浏览器里处理完点「继续」会重试当前页；也可点「跳过此页」或「跳过该站点」。无人值守场景用 `ABM_RESEARCH_ATTENTION_TIMEOUT_SECONDS`（默认 300 秒）自动跳过，设为 0 则一直等待；`ABM_RESEARCH_PAUSE_ON_INTERSTITIAL=false` 可恢复「直接跳过」的旧行为。
- 单用户自部署默认写本地目录（`ABM_MEDIA_ROOT`，默认 `data/media`）；
  托管环境建议使用 S3 / MinIO / R2，见 `.env.example` 中的 `ABM_S3_*`。
- 公众号导出是内联样式 HTML + 图片压缩包；小红书导出是 1080×1440 的图文卡片。
- 卡片渲染依赖 Playwright：

```bash
python -m pip install -e ".[render]"
python -m playwright install chromium
```

Docker 镜像已内置 Chromium 和 Noto Sans CJK 字体，并默认开启
`ABM_RENDER_NO_SANDBOX=1`（容器内非 root 运行时需要）。

## 发行版

服务端有两种发行方式，共用同一套代码和迁移：

| `ABM_EDITION` | 用途 | 账号 | 后台 |
|---|---|---|---|
| `single` | 开源自部署 | 只允许 1 个账号，关闭注册 | 系统设置 / 模型 / 存储 |
| `hosted` | 托管（私有 cloud 能力） | 多用户、审批、套餐 | 完整 |

单用户版保留登录，首次启动用 `ABM_BOOTSTRAP_ADMIN_*` 创建唯一管理员；社交登录会自动关闭。多租户、套餐、计费、用户管理属于私有 cloud 发行物，不在公开代码里。

`ABM_EDITION` 只选择行为档位：公开构建默认 `single`，设成 `hosted` 会因为缺少 `abm_server.cloud` 而启动失败；托管镜像才会带这个私有包。

额度由 `QuotaPolicy` 统一处理：

- 单用户版读 `ABM_LOCAL_*`（如 `ABM_LOCAL_GENERATIONS_PER_DAY`、`ABM_LOCAL_BROWSER_CONNECTIONS`），内容额度默认不限制
- 托管版读套餐字段，包括生成、token、图片、存储、采集页数、浏览器连接数、每连接会话数和优先级保留位

完整拆分方案见 [开源拆分：core / single / cloud](docs/open-core-split.md)。

## 社交登录

在 `ABM_PUBLIC_BASE_URL` 对应的域名下注册 OAuth 应用，回调地址统一为：

```text
https://<server>/api/v1/auth/social/<provider>/callback
```

| Provider | 环境变量 |
|---|---|
| WeChat | `ABM_SOCIAL_WECHAT_CLIENT_ID`、`ABM_SOCIAL_WECHAT_CLIENT_SECRET` |
| QQ | `ABM_SOCIAL_QQ_CLIENT_ID`、`ABM_SOCIAL_QQ_CLIENT_SECRET` |
| Google | `ABM_SOCIAL_GOOGLE_CLIENT_ID`、`ABM_SOCIAL_GOOGLE_CLIENT_SECRET` |
| GitHub | `ABM_SOCIAL_GITHUB_CLIENT_ID`、`ABM_SOCIAL_GITHUB_CLIENT_SECRET` |
| Microsoft | `ABM_SOCIAL_MICROSOFT_CLIENT_ID`、`ABM_SOCIAL_MICROSOFT_CLIENT_SECRET`、`ABM_SOCIAL_MICROSOFT_TENANT` |

未配置的 provider 不会显示。开启 `ABM_REGISTRATION_REQUIRE_APPROVAL=true` 时，社交自动注册的账号仍需管理员审批；已有账号只有在邮箱已验证时才会按同邮箱自动绑定。微信和 QQ 不返回邮箱，首次登录会进入补充邮箱页面，不会自动绑定已有账号。社交登录只用于 Web 账号，MCP 客户端仍然使用独立的 OAuth 2.1 授权。

## MCP 客户端

HTTP 客户端连接：

```text
https://<server>/mcp
```

MCP 使用 **OAuth 2.1**：

- 客户端自动读取受保护资源元数据，完成动态客户端注册、PKCE 授权和令牌交换。
- 授权页复用 ABM 账号登录和 `browser`、`account:read`、`account:write` scopes。
- API Key 只用于浏览器扩展 WebSocket，并由扩展换取短期视频桥令牌；不再作为 MCP 认证。

OAuth 授权时可以选择固定一个浏览器连接，或指定一组连接。浏览器工具需要扩展在线；多个浏览器任务使用 `browser_open_session` 获取 `browserSessionId`。连接被其他任务占用时返回 `ABM_CONNECTION_BUSY`。

公共注册端点：

```text
https://<server>/mcp/public
```

该端点不需要认证，只暴露 `account_register`，并按 IP 限流。

完整安装、OAuth 流程、工具目录和错误恢复说明见 [Agent MCP 安装使用手册](docs/mcp-agent-guide.md)，或访问服务端 `/docs/mcp`。

