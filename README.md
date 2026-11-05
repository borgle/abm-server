# ABM（a browser mcp） Server

ABM 是 **a browser mcp** 的简称。本项目是一个 Python 服务，用于将 MCP 客户端安全连接到用户自己的浏览器。

主要能力：

- Web 登录和单用户账号体系：首次启动用 `ABM_BOOTSTRAP_ADMIN_*` 创建唯一管理员，注册关闭。
- MCP 内置 OAuth 2.1 Authorization Code + PKCE + 动态客户端注册。
- 单账号管理多把 `abm_` API Key。
- 浏览器扩展 WebSocket 网关。
- 标准 MCP Streamable HTTP。
- 23 个 `browser_*` 浏览器工具和账号 / API Key 工具。
- 通知下发，以及 bridge、url、auto 三种视频投递模式；URL 源由扩展直连，bridge 仅使用临时文件中转，不持久化存储。
- 视频桥可从受信扩展自动获取 API Key 与扩展 ID。
- 用户 Web 控制台、Chrome 扩展 landing page 和 MCP 安装手册；控制台支持一键连接扩展、生成常见 Agent 的 MCP 配置，并展示扩展状态、工作流模板和按 Key 用量。
- 创作台：选题雷达、素材库、创作工坊、图片生成、公众号 HTML 和小红书 3:4 卡片导出、资产库与回收站。
- 页面支持中英文切换，默认跟随客户端语言（zh / en，其他回退 en），选择保存在 `abm.lang`。
- 账号支持邮箱验证、忘记密码、登录会话管理、数据导出和密码确认后的账号删除。
- 单用户版本地额度通过 `ABM_LOCAL_*` 配置（如每日生成次数、浏览器连接数），内容额度默认不限制。
- 控制台提供账号通知中心，展示额度、Key 和连接相关事件。
- MCP 工具描述、工具结果、HTTP 错误和 OAuth 错误描述使用英文规范文案；页面首屏在翻译完成前不会闪现中文模板。

多用户注册审批、套餐、计费、社交登录、用户管理和审计后台属于私有托管版，不在本仓库的公开构建中。

## 文档

完整文档见 [文档索引](docs/README.md)。常用入口：

- [完整架构设计](docs/architecture.md)
- [详细设计](docs/detailed-design.md)
- [数据流](docs/data-flow.md)
- [使用场景示例](docs/scenarios.md)
- [Local mode（数据不出本机）](docs/local-mode.md)
- [Agent MCP 安装使用手册](docs/mcp-agent-guide.md)
- [创作台设计方案](docs/creation-module.md) · [交互原型](docs/prototypes/creation-studio.html)
- [开发指南](AGENTS.md)

多用户、注册审批、套餐、计费、社交登录和管理后台属于私有托管版，文档不在本仓库。

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
  migrations/
docs/
tests/
```

## 开发

```bash
python -m pip install -e ".[dev]"
abm-server-migrate
python -m pytest
abm-server
```

默认 SQLite 数据库位于 `./data/abm.db`。

## Docker 部署

```bash
cp .env.docker.example .env
docker compose up -d --build
```

首次启动会执行 `abm-server-migrate`，并使用管理员初始化变量创建首个管理员。数据保存在
`abm_data` volume 中。生产环境请使用 HTTPS 反向代理、设置
`ABM_PUBLIC_BASE_URL`，并保持 `ABM_SESSION_COOKIE_SECURE=true`。通过
Cloudflare Tunnel 或本机反向代理访问时，同时设置
`ABM_FORWARDED_ALLOW_IPS=*`，让 Uvicorn 正确识别 HTTPS 和外部域名。

## 创作台：图片与排版

系统设置里的「套餐与模型」（单用户版显示为「本机模型」）可以配置对话和图片模型
（OpenAI Images 兼容接口），并在「参数配置」里设置每日生图次数、单次张数和存储上限。

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

公开构建默认 `ABM_EDITION=single`：只允许 1 个账号、关闭注册，保留登录；首次启动用
`ABM_BOOTSTRAP_ADMIN_*` 创建唯一管理员，社交登录自动关闭。

私有托管版通过 `ABM_EDITION=hosted` 启用多用户、套餐、审批、计费和管理后台。这些能力
不在公开代码里，公开构建设成 `hosted` 会因缺少 `abm_cloud` 启动失败。

额度由 `QuotaPolicy` 统一处理。单用户版读 `ABM_LOCAL_*`（如
`ABM_LOCAL_GENERATIONS_PER_DAY`、`ABM_LOCAL_BROWSER_CONNECTIONS`），内容额度默认不限制。

文档索引见 [docs/README.md](docs/README.md)。

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

完整安装、OAuth 流程、工具目录和错误恢复说明见 [Agent MCP 安装使用手册](docs/mcp-agent-guide.md)，或访问服务端 `/docs/mcp`。

