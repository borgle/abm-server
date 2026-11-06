# 创作台架构与媒体排版指南（Creation Studio）

## 1. 功能全景

创作台（`/creation/*` 与 `/api/v1/creation/*`）是内建于 `abm-server` 的端到端内容研究、AI 撰稿、配图生成、多平台排版导出与浏览器辅助发布工作台。

| 子模块 | 页面路由 | 核心代码模块 | 职责说明 |
|---|---|---|---|
| 工作台概览 | `/creation/overview` | `creation/service.py` | 项目、近期稿件、采集任务与发布状态总览 |
| 选题雷达 | `/creation/radar` | `creation/research/` | 多搜索引擎并行检索、正文抽取、可信度评分、验证码/登录墙暂停与恢复 |
| 素材库 | `/creation/library` | `creation/service.py` | 采集来源去重（`canonical_url`）、全文检索、标签筛选与引用管理 |
| 创作工坊 | `/creation/studio` | `creation/generation.py`, `compose.py` | 基于来源引用的多平台 AI 撰稿、版本历史（`CreationAssetVersion`）与在线编辑 |
| 图片与媒体 | `/creation/studio` | `creation/images.py`, `media.py` | OpenAI Images 兼容生图、参考图改图、本地上传、平台封面自动裁切 |
| 排版与导出 | `/creation/studio` | `creation/layout.py`, `render.py`, `exports.py` | 公众号内联样式 HTML + 图片包导出、小红书 1080×1440 图文卡片渲染导出 |
| 模板库 | `/creation/templates` | `creation/templates_data.py` | 内置写作结构与平台风格模板 |
| 资产与回收站 | `/creation/assets`, `/creation/trash` | `creation/maintenance.py` | 稿件与媒体资产归档、软删除回收站及到期自动清理 |
| 发布计划 | `/creation/publish` | `creation/publish.py` | 调用扩展独占会话打开目标平台创作后台并自动填充标题与正文 |

---

## 2. 选题雷达（Research Runner）

- **多引擎并行搜索**：支持对关键词生成检索计划（`planner.py`），按 `ABM_RESEARCH_PARALLEL_SEARCHES`（默认 2）并发驱动浏览器标签页（统一归入 `ABM · 检索 · 关键词` 标签组）。
- **人工介入暂停与恢复**：
  - 当检测到验证码或登录墙（Interstitial）且 `ABM_RESEARCH_PAUSE_ON_INTERSTITIAL=true` 时，任务状态转为 `attention`，记录受阻页面信息。
  - 用户在浏览器完成验证后可点击「继续」重试当前页，或选择「跳过此页」/「跳过该站点」。
  - 超过 `ABM_RESEARCH_ATTENTION_TIMEOUT_SECONDS`（默认 300s，0 表示无限等待）未处理时自动跳过受阻项。

---

## 3. 模型绑定与配额策略

- **模型解析（`creation/bindings.py`）**：
  - 单用户版（`ABM_EDITION=single`）：在 `/admin/plans`（界面显示为「本机模型」）配置对话模型、备用模型与图片模型，保存在 `creation_config.local`；支持用户自备 Key（BYOK）。
  - 托管版（`ABM_EDITION=hosted`）：通过 `abm_cloud.plans` 按账号所属套餐（`free` / `pro`）解析模型绑定。
- **额度控制（`quotas.py`）**：
  - 单用户版通过 `LocalQuotaPolicy` 读取 `ABM_LOCAL_*` 环境变量（每日生成次数、每月 Token、每日生图张数、存储字节上限、每月采集页数），`0` 代表无限制。

---

## 4. 媒体存储与平台尺寸预设

- **统一存储抽象（`storage/`）**：
  - `LocalStorage`（`ABM_STORAGE_BACKEND=local`）：文件保存在 `ABM_MEDIA_ROOT`（默认 `data/media`）。
  - `S3Storage`（`ABM_STORAGE_BACKEND=s3`）：支持 AWS S3、MinIO、Cloudflare R2，数据库仅保存 `storage_key`、字节数与 `sha256` 校验和。
- **平台封面自动裁切尺寸（`creation/images.py`）**：
  - 小红书（`xiaohongshu`）：`1080 × 1440`（3:4）
  - 微信公众号（`wechat`）：`900 × 383`（2.35:1）
  - 知乎（`zhihu`）：`1200 × 675`（16:9）
  - 视频号（`channels`）：`1080 × 1260`（6:7）
  - 通用主稿（`master`）：`1080 × 1080`（1:1）

---

## 5. 排版渲染与导出（微信公众号 / 小红书）

- **安全 Markdown 解析（`creation/layout.py`）**：使用 `markdown-it-py` 将正文解析为结构化块（标题、段落、列表、引用、代码块、表格、图片），禁用原始 HTML 标签以防止 XSS。
- **微信公众号导出（`wechat_html`）**：
  - 生成全部采用内联 `style="..."` 的纯净 HTML（不含 `<style>` 或外部 class），可直接粘贴至公众号后台。
  - 外链自动转换为文末脚注引用，配图打包为 `image-01` 等序号文件随 ZIP 一起下载。
- **小红书卡片导出（`xhs_cards`）**：
  - 支持多种视觉主题（如 `xhs-paper` 等），自动分页并使用 Playwright Chromium 渲染为 `1080 × 1440` PNG 卡片集。
