# Web UI 设计系统与国际化规范

## 1. 设计 Token 基线（`web/static/app.css`）

所有公开页面（Landing、Login、OAuth 授权页、MCP 手册）与工作台页面（`/console/*`、`/admin/*`、`/creation/*`）共用 `app.css` 顶层 `:root` 中定义的设计 Token，`workspace.css` 不得重复声明同名基础 Token。

### 1.1 字号标尺（Typography Scale）
正文与控件必须使用以下 Token（仅展示型大标题允许使用 `>= 17px` 的字面值或 `clamp()`）：
- `--text-2xs`: `9px`
- `--text-xs`: `10px`
- `--text-sm`: `11px`
- `--text-md`: `12px`
- `--text-base`: `13px`
- `--text-lead`: `15px`

### 1.2 尺寸与圆角 Token
- **控件高度**：`--control-sm: 28px`、`--control-md: 34px`、`--control-lg: 40px`、`--control-xl: 48px`
- **间距基准**：`--space-4: 10px`、`--space-8: 20px`
- **圆角尺寸**：`--radius-sm: 8px`、`--radius-xl: 18px`

---

## 2. 工作台壳层（Workspace Shell）

- **统一骨架**：`/console/*`、`/admin/*`、`/creation/*` 均继承 `templates/workspace.html`，通过 `<body data-app="..." data-section="..." data-edition="...">` 驱动侧边栏高亮与按需加载脚本。
- **缓存控制**：
  - HTML 响应强制设置 `Cache-Control: no-store`，确保版本升级与状态切换即时生效。
  - `/static/*` 静态资源使用 `_RevalidatingStaticFiles`（`Cache-Control: no-cache`），配合模板全局变量 `?v={{ asset_version }}`（基于静态文件内容计算的 SHA-256 前缀），兼顾缓存校验与 ES Module 嵌套导入的实时更新。

---

## 3. 双语国际化（i18n）机制

- **支持语言**：仅支持英文（`en`）与简体中文（`zh`），其他客户端语言一律回退至 `en`。
- **防首屏闪烁（`partials/lang_boot.html`）**：
  - `<head>` 内联脚本在首屏绘制前读取 `localStorage.getItem("abm.lang")` 或 `navigator.languages`。
  - 当目标语言与模板源语言不一致时，先挂载 `html.abm-lang-booting` 隐藏未翻译文本，待 `i18n.js` / `workspace-i18n.js` 完成 DOM 替换后立即移除。
- **DOM 标注规则**：
  - 使用 `data-i18n="key"` 绑定纯文本节点，`data-i18n-placeholder="key"` 绑定输入框占位符。
  - **严禁**在包裹了 `<input>` / `<select>` / `<textarea>` 的 `<label>` 元素上直接挂载 `data-i18n`（因为 `textContent` 赋值会销毁子表单控件），必须在 `<label>` 内部使用独立的 `<span data-i18n="...">` 包裹文案。
- **参数配置字典校验**：`admin/system_config.py` 中的每个分组（`config.group.<id>`）与配置项（`config.item.<key>.label` / `.description`）必须在 `workspace-i18n.js` 中提供完整英文翻译，由 `tests/test_config_i18n.py` 自动化守护。
