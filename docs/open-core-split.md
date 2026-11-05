# 开源拆分：core / single / cloud

> 状态：方案已确认，P1 已落地（edition 开关、注册与后台能力门禁）。
> 目标：开源单用户 server，托管多用户版本保持私有，不 fork 核心。

---

## 1. 结论

一套核心代码，两个发行物：

| 发行物 | 协议 | 内容 |
|---|---|---|
| `abm-core` | AGPL-3.0 | 浏览器网关、扩展协议、MCP、创作管线、存储、单用户认证 |
| `abm-server`（single） | AGPL-3.0 | 单用户发行版，依赖 core；登录、本机模型/存储配置 |
| `abm-cloud`（hosted） | 私有 | 多租户、套餐、计费、审批、团队、审计后台 |

公开仓库**不包含** `abm-cloud`，也不包含「切一下就能变托管」的开关。托管镜像安装私有包后才具备多租户能力。

## 2. 为什么不能靠配置开关

如果公开代码里已经有多租户、套餐、计费，别人只需要：

- 改 `ABM_EDITION=hosted`
- 去掉几个判断

就能起一个竞品托管。AGPL 只要求他们公开修改后的源码，不阻止他们运营服务。

因此：

- 公开代码里没有 hosted 实现
- `ABM_EDITION` 只选择行为档位，不是商业边界
- 公开构建默认 `single`；设成 `hosted` 会直接启动失败，因为找不到 `abm_cloud`
- 商业边界由「私有包 + 许可证」保证

日常开发仍在同一个私有仓库里完成：`abm_server/` 是 core + single，`abm_cloud/` 是托管实现。发布时由脚本生成不含 `abm_cloud` 的公开树，而不是直接公开当前仓库。

`abm_cloud` 已经是独立顶层包，可以单独 build/install；下一步是让公开仓库成为 core 的源，私有仓库只保留 `abm_cloud` 并依赖固定版本的 `abm-server`。

## 3. 模块归属

| 当前模块 | 归属 | 说明 |
|---|---|---|
| `extension_gateway/`、`tools/`、`video/` | core | 浏览器连接与工具分发 |
| `protocol.py`、`concurrency.py`、`usage.py` | core | 协议与基础服务 |
| `mcp/`、OAuth 服务 | core | 单用户也需要 MCP |
| `creation/`（research/generation/media/exports/render） | core | 创作台完整保留 |
| `storage/` | core | 本地 / S3 |
| `accounts/` 登录、会话、密码 | core | 单用户保留登录 |
| `editions.py`、能力依赖 | core | 发行版能力矩阵 |
| `api/routes/admin.py` 的用户 / 审批 / 审计 | cloud | 单用户版 404 |
| `admin/creation_config.py` 的套餐字段 | cloud | 单用户用本机配置 |
| 注册、审批、社交自动建号 | cloud | 单用户版关闭 |
| 用量计费、发票、订阅 | cloud | 当前仓库还没有 |
| 管理后台用户 / 审批 / 套餐页 | cloud | 单用户隐藏 |

## 4. 接口边界

### 4.0 拆分进度

已迁入 `abm_cloud/`：

- 用户列表、用户详情、禁用/审批、审计查询
- 套餐配置（独立存储 `creation_plans`，不再混在 core 的 `creation_config`）
- `PlanQuotaPolicy`
- 套餐模型绑定（对话与图片）
- 注册、社交自动建号、注册审批写入（`cloud/provisioning.py`）
- 用户状态更新、用户列表、审计查询（`cloud/admin_service.py`）
- MCP 的 `admin_*` 工具（`cloud/mcp_admin.py`）
- 套餐有效期与账号档位判断（`cloud/tiers.py`；core 只保留 `local` 档位）

core 只保留：

- 单账号 bootstrap、登录、会话
- `LocalQuotaPolicy`
- 本机模型配置（`/api/v1/admin/local-model`）
- 本地模型绑定
- 注册/社交入口的**薄封装**：没有 cloud 包时直接返回 403

待迁移：

- 用量统计与审计写入
- 公开测试的账号 fixture

### 4.1 Edition（已实现）

```python
@dataclass(frozen=True)
class Edition:
    multi_user: bool
    self_registration: bool
    plans: bool
    approvals: bool
    audit: bool
    admin_users: bool
    billing: bool
```

- `ABM_EDITION=single|hosted`
- `require_capability("admin_users")` 在服务端拦截路由，不依赖前端隐藏
- 单用户版启动时强制关闭社交登录，避免绕过单账号限制

### 4.2 QuotaPolicy（已实现）

```python
class QuotaPolicy(Protocol):
    async def limits(...): ...
    async def browser_limits(...): ...
```

- `LocalQuotaPolicy`：读 `ABM_LOCAL_*` 环境变量，内容额度默认不限制
- `PlanQuotaPolicy`：读套餐 JSON，包含生成、token、图片、存储、采集页数、浏览器连接/会话/保留位
- 生成、图片、存储、采集、浏览器租约都已改为走策略

浏览器并发（`browserConnections` / `browserSessions` / `reservedPrioritySlots`）
已经进入套餐字段，由网关在注册和租约分配时读取；单用户版走 `ABM_LOCAL_*`。

### 4.3 RegistrationPolicy（待实现）

单用户版：只允许 bootstrap 管理员，注册接口 403，社交登录关闭。
托管版：沿用现有注册 + 审批 + 社交登录。

## 5. 数据库

- **共用一套 schema 和迁移**，不做单用户精简表
- single 不使用的表保持为空（审批、审计、套餐等）
- 迁移只发一条线，避免两边结构漂移

## 6. 发布与仓库

推荐顺序：

1. 当前仓库保持私有，继续做 core 抽取
2. 公开 `abm-core` + `abm-server`（AGPL）
3. 私有 `abm-cloud` 依赖固定版本的 core
4. 公开仓库通过脚本从私有 monorepo 同步 core 目录，避免手工复制

不推荐：

- 两份 server 代码各改各的
- 公开仓库保留 cloud 目录再用协议限制（代码仍可见、可复制）

## 7. 单用户版行为

| 项 | 行为 |
|---|---|
| 账号 | 只允许 1 个，首次启动用 `ABM_BOOTSTRAP_ADMIN_*` 创建 |
| 登录 | 保留（Web、MCP OAuth 都需要） |
| 注册 | 关闭，接口 403，页面 404 |
| 社交登录 | 启动时关闭 |
| 后台 | 保留系统设置、模型连接、存储、数据保留；隐藏用户/审批/审计 |
| 套餐 | 不展示套餐概念，本机额度走环境变量 |
| 创作台 | 完整保留 |
| 扩展 / MCP | 与托管版一致 |

## 8. 实施阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | Edition 开关、能力门禁、注册关闭、后台裁剪 | 已完成 |
| P2 | QuotaPolicy 抽象（生成 / 图片 / 存储 / 浏览器并发） | 已完成 |
| P3 | 单用户模型配置页（去掉套餐概念） | 已完成 |
| P4 | core 抽取与公开仓库、LICENSE | 进行中：cloud 已拆成顶层 `abm_cloud` 包；公开树不含 cloud、带单用户测试；下一步公开仓库作为 core 源，私有仓库依赖 `abm-server` |
| P5 | cloud 私有包与 billing 接口 | 待开始 |

## 9. 测试策略

- 现有测试默认 `hosted`，保持托管行为不变
- 新增 `single` fixture：注册 403、管理接口 404、页面链接隐藏、创作与 MCP 可用
- 后续 QuotaPolicy 用同一批用例跑两种策略

## 10. 许可证

- core / single：AGPL-3.0
- cloud：私有许可
- 扩展仓库当前没有 LICENSE，开源前补 MIT 或 AGPL（与 server 保持一致更简单）

AGPL 的作用是阻止闭源二次分发；它不阻止别人基于 core 自建托管，真正的壁垒是私有 cloud 功能、运维与品牌。
