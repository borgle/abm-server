/**
 * 控制台工作流模板。文案按页面语言切换，prompt 可直接复制给 Agent。
 */
export const WORKFLOWS = {
  en: [
    {
      id: "extract",
      title: "Browse and extract page data",
      description: "Open a page, wait for it to settle, and return structured data.",
      prompt:
        "Use ABM to open <URL>, wait for the page to load, extract the main heading and the first 5 links, and return them as JSON.",
    },
    {
      id: "form",
      title: "Fill and submit a form",
      description: "Fill fields, verify values, then submit with confirmation.",
      prompt:
        "Use ABM to open <URL>, fill <field selector> with <value>, verify the value, then click <submit selector>. Stop and ask me before submitting if the page requests sensitive data.",
    },
    {
      id: "upload",
      title: "Upload a local file",
      description: "Use a local absolute path so bytes never pass through the server.",
      prompt:
        "Use browser_set_files_native with selector <input selector> and the local absolute path <file path>. Verify the file name appears on the page before submitting.",
    },
    {
      id: "video",
      title: "Download a video and inject it",
      description: "Direct URL delivery, then set the staged video into a file input.",
      prompt:
        "Use browser_stage_video with url <video URL>, fileName <name.mp4>, delivery url. Then call browser_set_video_to_page with selector <input selector>. Report the final file size.",
    },
    {
      id: "network",
      title: "Capture page API responses",
      description: "Record network requests and extract JSON responses.",
      prompt:
        "Use browser_network_intercept with cmd start on the current tab, reload the page, then list requests whose URL contains <keyword>. Read the matching JSON response and summarize the fields I care about.",
    },
    {
      id: "multi",
      title: "Multi-tab / multi-account workflow",
      description: "Use browser sessions and tab reuse for parallel work.",
      prompt:
        "Open a browser session, navigate to <URL>, and use reuseKey <client-name> so this client keeps its own tab. Repeat for each account, and report which session handled which account.",
    },
    {
      id: "qa",
      title: "Page regression check",
      description: "Walk a flow, wait for elements, and capture failures.",
      prompt:
        "Use ABM to load <URL>, click <selector>, wait for <result selector>, and verify the expected text <text>. If anything fails, return the failing step, selector, and a screenshot if available.",
    },
    {
      id: "research",
      title: "Competitor price research",
      description: "Collect prices from several pages into a table.",
      prompt:
        "Open each URL in <URL list>, extract the product name, price, and availability, and return a markdown table. Use a separate tab or reuse key per site and do not submit any forms.",
    },
  ],
  zh: [
    {
      id: "extract",
      title: "浏览并提取页面数据",
      description: "打开页面，等待稳定后返回结构化数据。",
      prompt:
        "用 ABM 打开 <URL>，等待页面加载完成，提取主标题和前 5 个链接，以 JSON 返回。",
    },
    {
      id: "form",
      title: "填写并提交表单",
      description: "填写字段、校验值，再在确认后提交。",
      prompt:
        "用 ABM 打开 <URL>，把 <字段选择器> 填为 <值>，校验值正确后点击 <提交按钮选择器>。如果页面要求填写敏感信息，先停下来问我。",
    },
    {
      id: "upload",
      title: "上传本机文件",
      description: "使用本机绝对路径，文件字节不经过服务器。",
      prompt:
        "用 browser_set_files_native，选择器为 <file input 选择器>，路径为 <本机绝对路径>。提交前确认页面显示了正确的文件名。",
    },
    {
      id: "video",
      title: "下载视频并注入页面",
      description: "URL 直连下载，然后把暂存视频写进文件输入框。",
      prompt:
        "用 browser_stage_video，url 为 <视频 URL>，fileName 为 <name.mp4>，delivery 为 url；然后调用 browser_set_video_to_page，选择器为 <file input 选择器>，最后报告文件大小。",
    },
    {
      id: "network",
      title: "抓取页面 API 响应",
      description: "记录网络请求并提取 JSON 响应。",
      prompt:
        "用 browser_network_intercept 在当前标签页执行 start，刷新页面，然后列出 URL 包含 <关键词> 的请求，读取匹配的 JSON 响应并总结我关心的字段。",
    },
    {
      id: "multi",
      title: "多标签 / 多账号操作",
      description: "用浏览器会话和标签复用并行处理多个账号。",
      prompt:
        "打开一个浏览器会话，导航到 <URL>，用 reuseKey <客户名> 让这个客户使用独立标签。每个账号重复一次，并报告哪个会话处理了哪个账号。",
    },
    {
      id: "qa",
      title: "页面回归检查",
      description: "走一遍流程，等待元素，并记录失败点。",
      prompt:
        "用 ABM 打开 <URL>，点击 <选择器>，等待 <结果选择器>，确认文本为 <预期文本>。任何一步失败时，返回失败步骤、选择器和截图（如果可用）。",
    },
    {
      id: "research",
      title: "竞品价格调研",
      description: "从多个页面收集价格并整理成表格。",
      prompt:
        "依次打开 <URL 列表> 中的页面，提取商品名、价格和库存状态，返回 Markdown 表格。每个站点使用独立标签或 reuseKey，不要提交任何表单。",
    },
  ],
};
