# ABM Server 详细设计

## 1. 模块职责与并发边界

### 1.1 数据库与连接管理（`database.py`）
- **SQLite 可移植优化**：使用 SQLite 时启用 `NullPool`，并在每次连接建立时自动执行：
  - `PRAGMA foreign_keys=ON`
  - `PRAGMA busy_timeout=15000`
  - `PRAGMA journal_mode=WAL`
- **PostgreSQL 生产支持**：通过 `asyncpg` 驱动与连接池（`pool_pre_ping=True`）支持高并发异步访问。
- **时区规范**：所有时间戳统一使用带时区的 UTC（`DateTime(timezone=True)`）。

### 1.2 并发控制与限流（`concurrency.py`）
- **`SlidingWindowLimiter`**：进程内滑动窗口限流器，保护登录、密码重置等敏感入口（默认 15 分钟内最多 5 次尝试，超限返回 `429 ABM_RATE_LIMITED`）。
- **`KeyedLockPool`**：按 `user_id` 或资源键加锁的异步互斥锁池，确保 API Key 创建数量检查等复合操作在同一用户维度串行化，防止并发超额创建。

### 1.3 认证与安全模型（`auth/`、`accounts/`、`api_keys/`）
- **密码哈希**：使用 Argon2id（`argon2-cffi`），登录时若检测到参数升级需求会自动透明重哈希。
- **会话与 CSRF**：
  - 登录成功后签发随机 `session_token` 与 `csrf_token`，数据库仅存其 SHA-256 摘要（`AccountSession.token_hash` / `csrf_hash`）。
  - 所有基于 Cookie 的写请求（`POST` / `PUT` / `PATCH` / `DELETE`）通过 `require_csrf` 强制校验 `X-CSRF-Token` 请求头与 `Origin` / `Referer` 同源性。
  - 后台定时任务每 12 小时执行 `cleanup_account_sessions`，按 `ABM_SESSION_RETENTION_DAYS`（默认 90 天）清理过期或已吊销会话。
- **API Key 生命周期**：
  - 格式：`abm_<prefix>_<secret>`。
  - 创建时仅返回一次明文，数据库存 `public_prefix` 与完整 Key 的 SHA-256 摘要。
  - 吊销 API Key 或停用/删除账号时，立即通过 `ExtensionGateway` 主动断开关联的 WebSocket 连接（关闭码 `1008`）。

### 1.4 扩展网关与会话租约（`extension_gateway/`）
- **握手流程**：扩展连接 `/ws` 后必须在 `hello_timeout_ms`（默认 10s）内发送 `session.hello`（携带 API Key 与扩展版本），校验通过后服务端返回 `session.ready`。
- **连接池与租约分配**：
  - 支持同一 API Key 下多浏览器实例在线，以 `connection_id` 区分。
  - Agent 调用 `browser_open_session` 时，网关根据 OAuth 令牌绑定的连接策略（`auto` / `pinned` / `allowlist`）及 `QuotaPolicy.browser_limits` 分配独占租约 `browserSessionId`。
  - 发布等高优先级任务可使用预留槽位（`reserved_priority_slots`），普通采集任务不会挤占预留位。
- **Pending 调用管理**：每次 `tool.invoke` 生成唯一 `call_id` 并注册 `asyncio.Future`；连接断开或超时时立即以结构化 `GatewayCallError` 唤醒等待协程。

### 1.5 视频协调服务（`video/service.py`）
- **双通道投递策略（`ABM_VIDEO_DELIVERY`）**：
  - `url` 模式：若输入已是远程 URL，直接通过 `chrome_download_video_from_url` 下发给扩展直连拉取；若输入是 base64，暂存至临时文件并生成带一次性签名令牌的 `/api/v1/downloads/{job_id}` 供扩展拉取。
  - `bridge` 模式：将视频写入本机临时目录（`ABM_VIDEO_TEMP_DIR`），由同源页面 `/video-bridge` 使用短期 `abm_bridge_*` 令牌分片拉取（默认 20MB/片），通过 `chrome.runtime.sendMessage` 推送至扩展内存暂存区。
- **资源回收保证**：无论投递完成、失败或超过 `video_job_ttl_ms`（默认 30 分钟），临时文件均立即删除，服务端不持久化任何视频字节。

### 1.6 运行时配置与模型加密（`admin/`）
- **Provider 密钥加密（`admin/creation_config.py`）**：模型连接的 API Key 使用 `ABM_CREATION_SECRET_KEY`（32 字节 Base64 密钥）通过 AES-GCM（12 字节随机 Nonce）加密后存入 `settings` 表；前端接口仅返回 `apiKeyLast4` 与 `hasApiKey`。
- **动态系统参数（`admin/system_config.py`）**：支持在管理台 `/admin/config` 对 6 大分组参数进行数据库级覆盖、类型与范围校验、脱敏审计以及 JSON 导入/导出。
