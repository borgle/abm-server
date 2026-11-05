# 创作台：图片生产与排版导出（设计草案）
> 范围：开源单用户版 core。托管版的多用户、套餐、审批、计费不在本仓库。

> 状态：P1–P3 已实现（对象存储、图片生成、公众号 HTML、小红书卡片）；P4 未开始。
> 范围：图片/视频模型抽象、资产图片存储与配额、公众号 HTML 导出、小红书图文卡片渲染。
> 关联：`docs/architecture.md`（模块边界）、`docs/ui-design-system.md`（视觉规范）。

---

## 1. 目标

1. 创作台能按平台生产配图：封面图、文中配图、小红书图文卡片。
2. 图片模型可替换：内置 OpenAI Images API 兼容适配器，也能接其他图片/视频服务。
3. 两种交付都要有：
   - 公众号：Markdown → 内联样式 HTML，可直接粘贴进编辑器。
   - 小红书：Markdown → 分页图文卡片（PNG，1080×1440）。
4. 产出物进资产库：有版本、可替换、可回退，计入套餐存储与生成额度。

## 2. 非目标

- 不做在线设计器（拖拽画布）。
- 不做视频剪辑；视频模型只预留生成接口。
- 不做自动发布；导出仍是「生成文件 + 人工粘贴/上传」。

---

## 3. 总体架构

```
Markdown 版本 ──► 解析器（markdown-it-py）──► Block 列表
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
           公众号渲染器                       小红书分页渲染器
        （Python 字符串模板，              （HTML 模板 + Playwright，
          内联 style，无外链）               按高度分页后逐页截图）
                    │                                   │
                    ▼                                   ▼
             export.html                       card-01.png … card-N.png
                    └──────────────┬────────────────────┘
                                   ▼
                         blob 存储 + creation_exports / creation_media
```

图片生成与排版互不依赖，但共用存储、配额和资产版本。

---

## 4. 数据模型

### 4.1 `creation_media`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str(36) | 主键 |
| user_id | str(36) | 归属 |
| project_id | str(36) null | 冗余便于筛选 |
| asset_id | str(36) null | 可独立于资产存在（如项目封面） |
| asset_version_id | str(36) null | 绑定到具体版本，保证版本可回退 |
| kind | str(16) | cover / inline / card |
| platform | str(32) | xiaohongshu / wechat / zhihu / master |
| role | str(16) | generated / uploaded / rendered |
| status | str(16) | pending / ready / failed / trashed |
| prompt / negative_prompt | Text | 生成参数，便于复现 |
| provider_id / model | str | 生成来源 |
| seed | int null | 支持时记录 |
| width / height | int | 像素 |
| mime | str(32) | image/png、image/jpeg、video/mp4 |
| storage_key | str(255) | 相对路径，如 `ab/cd/<sha>.png` |
| bytes | int | 计费用 |
| sha256 | str(64) | 去重 |
| meta | JSON | 原始响应摘要、耗时、参考图 id |
| created_at / trashed_at / purge_after | datetime | 复用回收站策略 |

索引：`(user_id, created_at)`、`(asset_id, kind)`、`(user_id, sha256)`。

### 4.2 `creation_exports`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str(36) | 主键 |
| user_id / asset_id / asset_version_id | str(36) | 来源版本 |
| target | str(16) | `wechat_html` / `xhs_cards` |
| style_id | str(32) | 模板标识，如 `wechat-classic`、`xhs-paper` |
| options | JSON | 字号、是否含图注、页码等 |
| status | str(16) | pending / ready / failed |
| file_key | str(255) null | HTML 或 zip |
| files | JSON | 卡片列表 `[{mediaId, page}]` |
| error_code / error_message | str | `ABM_*` |
| created_at / expires_at | datetime | 导出物保留 7 天 |

导出物也计入存储配额。

---

## 5. 模型 Provider 抽象

### 5.1 接口

```python
@dataclass
class GeneratedImage:
    data: bytes
    mime: str
    width: int
    height: int

@dataclass
class ImageResult:
    images: list[GeneratedImage]
    model: str
    raw: dict

class ImageProvider(Protocol):
    kind: str  # "openai-images" | "custom"

    async def generate(
        self,
        *,
        prompt: str,
        size: str,              # "1024x1536" 等，由平台预设推导
        n: int = 1,
        seed: int | None = None,
        reference: bytes | None = None,   # 支持图生图/改图时传入
    ) -> ImageResult: ...
```

视频接口先定义、不实现：

```python
class VideoProvider(Protocol):
    async def submit(self, *, prompt: str, duration: int, size: str, image: bytes | None) -> str: ...
    async def poll(self, job_id: str) -> VideoJob: ...  # queued/running/ready/failed + url
```

### 5.2 适配器

- `openai-images`：`POST {base_url}/images/generations`，`response_format=b64_json`；有参考图时走 `/images/edits`（multipart）。兼容 OpenAI、newapi、以及大部分聚合网关。
- `custom`：配置里声明请求模板与响应取值路径（`jsonPath`），用于非兼容服务。仅在确有需求时实现，避免过度设计。
- 视频：`openai-video`（提交/轮询）、`custom`。

### 5.3 配置

扩展现有 `creation_config.providers[]`：

```json
{
  "id": "img_openai",
  "kind": "image",
  "adapter": "openai-images",
  "baseUrl": "https://api.example.com/v1",
  "apiKey": "<encrypted>",
  "models": ["gpt-image-1"],
  "defaultModel": "gpt-image-1",
  "capabilities": { "maxN": 4, "sizes": ["1024x1024", "1024x1536", "1536x1024"], "edit": true }
}
```

套餐新增：`imageProviderId`、`imageModel`、`imageGenerationsPerDay`、`imageMaxN`。
（与上一轮讨论一并落地：`concurrentBrowsers`、`concurrentSessions`、`storageBytes` 强制校验。）

---

## 6. 生成流程

1. 校验资产归属、套餐额度（当日图片次数、存储余量、并发）。
2. 组装 prompt：用户输入 + 平台预设（比例、安全区、禁词）+ 标题/摘要（可选自动生成）。
3. 调 provider，超时 120s，失败重试 1 次（429/5xx）。
4. 按平台裁切：封面统一缩放到精确尺寸（小红书 1080×1440、公众号 900×383、知乎 1200×675、视频号 1080×1260、主稿 1080×1080）。
5. 校验返回：mime 白名单、解码尺寸、单张 ≤ 10MB。
5. 去重（sha256）→ 写 blob → 落 `creation_media`。
6. 返回候选列表；用户选定后写 `role=cover/inline` 并绑定 `asset_version_id`。

错误码：

| 场景 | 码 | 提示 |
|---|---|---|
| 未配置图片模型 | `ABM_CREATION_IMAGE_NOT_CONFIGURED` | 联系管理员配置 |
| 当日次数用尽 | `ABM_CREATION_IMAGE_QUOTA` | 明天再来或升级套餐 |
| 存储超限 | `ABM_CREATION_STORAGE_FULL` | 清理回收站或扩容 |
| 供应商失败 | `ABM_CREATION_IMAGE_FAILED` | 可重试，附供应商摘要 |
| 渲染器不可用 | `ABM_CREATION_RENDER_UNAVAILABLE` | 安装渲染组件 |

---

## 7. 存储与配额

图片、视频、导出文件都走对象存储，**数据库只存 key、大小和 sha256**。

### 7.1 后端

| 后端 | 用途 | 配置 |
|---|---|---|
| `s3`（默认给托管版） | MinIO / AWS S3 / Cloudflare R2 | `ABM_STORAGE_BACKEND=s3` + endpoint / bucket / key |
| `local`（默认给单用户版） | 本机目录，零依赖 | `ABM_STORAGE_BACKEND=local` + `ABM_MEDIA_ROOT` |

```ini
ABM_STORAGE_BACKEND=s3
ABM_S3_ENDPOINT_URL=http://127.0.0.1:9000
ABM_S3_BUCKET=abm-media
ABM_S3_ACCESS_KEY_ID=...
ABM_S3_SECRET_ACCESS_KEY=...
ABM_S3_REGION=us-east-1
ABM_S3_PREFIX=abm
ABM_S3_ADDRESSING_STYLE=path
ABM_S3_USE_SSL=false
```

- MinIO 本地开发用 `docker compose` 起一个，bucket 首次写入时自动创建（可关）。
- `boto3` 作为可选依赖 `abm-server[s3]`，未安装且配置为 s3 时启动即报错，不静默降级。
- 对象 key：`media/{user_id}/{sha[:2]}/{sha}.{ext}`、`exports/{user_id}/{export_id}/{file}`。
- 读取走鉴权路由 `/api/v1/creation/media/{id}/file`，不暴露 bucket 或目录；托管版后续可加短时效签名 URL。
- 去重按 `(user_id, sha256)`：命中已有记录时复用存储对象，不重复计费。

### 7.2 配额

- 存储统计：`sum(creation_media.bytes) + sum(creation_exports.file_bytes)`，按用户缓存 60 秒。
- 图片生成按「当日次数」计，导出按「文件大小」计入存储。
- 删除走回收站：`trashed_at` 后 10 天清理，同时删除对象存储文件（引用计数为 0 时）。
- 上传图片（非生成）同样入库、计费、去重。

---

## 8. 排版管线

### 8.1 解析

新增依赖 `markdown-it-py`，统一输出 Block AST：heading / paragraph / list / quote / code / image / table / hr。
客户端 `markdown.js` 只负责预览，导出以服务端解析为准，避免两端规则漂移；两边用同一份测试样例校验。

### 8.2 公众号 HTML 导出

- 纯字符串渲染，不依赖浏览器。
- 所有样式内联（`style="..."`），不输出 `class`/`id`/`<style>`，兼容公众号编辑器清洗规则。
- 图片：公众号编辑器不允许正文直接引用外链图片，粘贴 data URI 也不可靠。默认策略是「占位 + 图片包」：HTML 里保留图注和序号，同时导出 `images.zip`，用户粘贴后按序号上传。若后续接入公众号素材库接口，再改成自动上传。
- 外链：转成「文字（链接）」形式，因为公众号正文不允许可点击外链。
- 代码块：等宽字体 + 浅底 + 保留缩进，不引入高亮库。
- 输出单文件 `export.html`，同时提供「复制全文」按钮（前端 `ClipboardItem text/html`）。

### 8.3 小红书图文卡片

- 渲染器：Playwright（Chromium），作为可选依赖 `abm-server[render]`；Docker 镜像内置。
- 流程：
  1. 服务端生成 `card-doc.json`（块 + 主题 + 元信息）。
  2. 打开本地模板页，注入块列表。
  3. 页面内 JS 按容器高度分页：逐块累加，遇到标题与后续内容分离时提前换页，列表/引用不拆断。
  4. 逐页 `element.screenshot()`，1080×1440，输出 PNG。
- 模板首版三套：`xhs-paper`（米白）、`xhs-ink`（深色）、`xhs-grid`（网格）。封面单独模板：大标题 + 副标题 + 可选配图。
- 封面图使用图片生成模块产出的 1080×1440 精确尺寸版本。
- 字体：Noto Sans SC（OFL）随镜像安装，避免服务器缺字。
- 并发：全局信号量 1，渲染 6 页约 2–4 秒；超时 60 秒。
- 渲染失败降级：返回错误码，前端提示改用「公众号 HTML」或重试。

### 8.4 图片在排版中的位置

- 卡片模板预留图片槽位，引用 `creation_media` 的 blob（通过本地路径注入，不走外网）。
- 公众号导出的图片策略见 8.2：占位 + `images.zip`，避免依赖外链或 base64。

---

## 9. API 契约

```
POST   /api/v1/creation/assets/{asset_id}/media/generate
GET    /api/v1/creation/assets/{asset_id}/media
GET    /api/v1/creation/media/{media_id}
GET    /api/v1/creation/media/{media_id}/file
PATCH  /api/v1/creation/media/{media_id}          # role / caption / 绑定版本
DELETE /api/v1/creation/media/{media_id}          # 进回收站
POST   /api/v1/creation/media/{media_id}/restore

POST   /api/v1/creation/assets/{asset_id}/exports
GET    /api/v1/creation/exports/{export_id}
GET    /api/v1/creation/exports/{export_id}/file  # html 或 zip
DELETE /api/v1/creation/exports/{export_id}

GET    /api/v1/creation/image-presets            # 平台尺寸与安全区
```

生成请求示例：

```json
{
  "kind": "cover",
  "platform": "xiaohongshu",
  "prompt": "小户型玄关收纳，暖光，实拍感",
  "n": 4,
  "size": "1024x1536",
  "assetVersionId": "…"
}
```

导出请求示例：

```json
{ "target": "xhs_cards", "styleId": "xhs-paper", "options": { "showPageNumber": true } }
```

---

## 10. UI 改动

- 创作工坊右栏新增「配图」区块：当前封面缩略图、生成按钮、候选网格。
- 生成弹窗：平台切换时自动带出比例（小红书 3:4、公众号 2.35:1、方形 1:1）。
- 新「导出」弹窗：两个页签（公众号 HTML / 小红书卡片），模板选择、预览、下载/复制。
- 素材库卡片显示封面缩略图；回收站同样支持图片。
- 全部文案补 `zh`/`en`。

---

## 11. 测试与验收

单元：

- provider 响应解析（b64、URL 两种）、错误映射、超时重试。
- 配额：次数、存储、并发；边界与并发请求。
- Markdown → Block：中英文、嵌套列表、表格、代码块、图片。
- 公众号 HTML：无 `class`/`style` 标签、外链处理、图片内联。
- 分页：标题不落单、列表不拆断、超长段落截断策略。

集成：

- 生成 → 落库 → 读文件 → 删除 → 回收站恢复。
- 导出 → zip 下载 → 页数与顺序一致。
- 无渲染组件时返回 `ABM_CREATION_RENDER_UNAVAILABLE`。

浏览器验证：`chrome://extensions` 加载扩展，走一遍「生成封面 → 导出小红书卡片 → 公众号复制」。

---

## 12. 里程碑

| 阶段 | 内容 | 预估 | 状态 |
|---|---|---|---|
| P1 | provider 抽象 + OpenAI Images + 对象存储（MinIO/本地）+ 配额 + 封面生成 UI | 1.5–2 周 | 已完成 |
| P2 | markdown-it 管线 + 公众号 HTML 导出 + 复制 | 1 周 | 已完成 |
| P3 | Playwright 渲染器 + 分页 + 3 套卡片模板 | 2 周 | 已完成 |
| P4 | 视频 provider 接口 + 批量导出 + 模板扩展 | 1 周 | 未开始 |

## 13. 依赖

| 依赖 | 范围 | 说明 |
|---|---|---|
| `markdown-it-py` | 核心 | Markdown → Block，P2 起用 |
| `boto3` | 可选 `[s3]` | 只在 `ABM_STORAGE_BACKEND=s3` 时需要 |
| `playwright` | 可选 `[render]` | 小红书卡片渲染，Docker 镜像默认安装 |

## 14. 风险

- **图片成本**：按张计费，需在生成前展示预计消耗，避免误点 4 张。
- **供应商差异**：不同网关对 `size`、`n`、`response_format` 支持不一，适配器需做能力探测与降级。
- **公众号样式清洗**：编辑器会重写部分标签，模板需以真实粘贴验证。
- **字体体积**：Noto Sans SC 完整字重较大，镜像只装 Regular/Medium/Bold 三个。
- **渲染稳定性**：Playwright 在低配机器上可能 OOM，需限制并发并提供降级路径。

## 15. 开放问题

1. 托管版的图片额度按「张」还是按「token/积分」计？
2. 小红书卡片是否需要支持上传自定义底图/品牌模板？
3. 公众号导出是否需要支持「草稿箱 API」（目前只做 HTML 复制）？
