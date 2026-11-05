import { initPageLanguage } from "./i18n.js";

const translations = {
  en: {
    "page.title": "ABM · Connect your browser to AI agents",
    "nav.features": "Features",
    "nav.install": "Install",
    "nav.mcp": "MCP",
    "nav.guide": "Guide",
    "nav.console": "Console",
    "nav.login": "Sign in",
    "nav.register": "Request access",
    "hero.title": "Connect your own browser <br class=\"hero-break\" />to AI agents, <em>securely.</em>",
    "hero.lead":
      "ABM connects a real browser through a Chrome extension, so MCP clients can open tabs, read pages, fill forms, download files, and deliver videos without handing account credentials to the model.",
    "hero.download": "Download Chrome extension",
    "hero.guide": "Read the MCP guide",
    "hero.register": "Request an account",
    "hero.note":
      "The extension is not yet on the Chrome Web Store. Download the ZIP from GitHub Releases and load it as an unpacked extension.",
    "features.eyebrow": "CAPABILITIES",
    "features.title": "Real browser, real pages, real actions",
    "features.lead":
      "Browser tools run in the extension on the user's machine. The server only handles routing, authentication, and audit.",
    "features.tabs.title": "Tabs & navigation",
    "features.tabs.body":
      "Create, switch, update, and close tabs, open URLs, and read the current page.",
    "features.dom.title": "DOM & interaction",
    "features.dom.body":
      "Query and wait for elements, click, fill forms, type with the keyboard, and extract text.",
    "features.script.title": "Scripts & network",
    "features.script.body":
      "Run scripts in the page's main world and intercept network requests through CDP.",
    "features.upload.title": "Files & uploads",
    "features.upload.body":
      "Upload single files, multiple files, URL files, and local paths, including base64 assembly.",
    "features.video.title": "Video delivery",
    "features.video.body":
      "Receive base64 or URL videos, stage them, and inject them into page file inputs.",
    "features.account.title": "Accounts & audit",
    "features.account.body":
      "Registration approval, API Key limits, OAuth sign-in, administrator actions, and audit events.",
    "install.eyebrow": "GET STARTED",
    "install.title": "Connect in three steps",
    "install.lead":
      "From a downloaded ZIP to a live browser connection, in about two minutes.",
    "install.step1.title": "Install the extension",
    "install.step1.body":
      "Download the latest ZIP from GitHub Releases, enable Developer mode at <code>chrome://extensions</code>, and load the unpacked extension.",
    "install.step2.title": "Register and create an API Key",
    "install.step2.body":
      "Sign in to the console, create an API Key, enter the server URL and key in the extension settings, and connect.",
    "install.step3.title": "Configure your MCP client",
    "install.step3.body":
      "In your MCP client, connect to <code>{issuer}/mcp</code> and sign in with OAuth. The consent page lets you choose allowed browser connections.",
    "install.download": "Get the latest release",
    "install.register": "Create an account",
    "install.cardTitle": "Chrome loading steps",
    "install.cardStep1": "Unzip the downloaded extension ZIP.",
    "install.cardStep2": "Open <code>chrome://extensions</code>.",
    "install.cardStep3": "Turn on Developer mode in the top-right corner.",
    "install.cardStep4": 'Click "Load unpacked" and select the extracted folder.',
    "install.cardStep5": "Open the extension options and enter the server URL and API Key.",
    "mcp.eyebrow": "MCP CONNECTION",
    "mcp.title": "OAuth with browser policy",
    "mcp.lead":
      "The MCP client discovers the server and completes browser sign-in automatically. During consent you choose a fixed browser or a pool of browser connections.",
    "mcp.recommended": "Recommended",
    "mcp.oauth.title": "OAuth 2.1 sign-in",
    "mcp.oauth.body":
      "The client reads the protected-resource metadata, registers dynamically, and opens the ABM sign-in page. After consent, no key needs to be copied manually.",
    "mcp.compatible": "Isolation",
    "mcp.key.title": "Browser task sessions",
    "mcp.key.body":
      "A client can be fixed to one browser or allowed to use a pool. Each browser task gets a server-issued browserSessionId so parallel work does not collide.",
    "mcp.resourceLabel": "Resource",
    "mcp.metadataLabel": "Metadata",
    "mcp.guide": "Read the full installation and tool guide",
    "cta.eyebrow": "READY",
    "cta.title": "Let agents operate your browser, not your passwords",
    "cta.body":
      "The extension handles browser execution. The server handles identity, permissions, and connectivity. The two repositories deploy and upgrade independently.",
    "cta.download": "Download extension",
    "cta.guide": "MCP guide",
  },
  zh: {
    "page.title": "ABM · 把浏览器安全接入 AI Agent",
    "nav.features": "功能",
    "nav.install": "安装",
    "nav.mcp": "MCP",
    "nav.guide": "手册",
    "nav.console": "控制台",
    "nav.login": "登录",
    "nav.register": "申请使用",
    "hero.title": "把用户自己的浏览器 <br class=\"hero-break\" />安全接入 <em>AI Agent</em>",
    "hero.lead":
      "ABM 通过 Chrome 扩展连接真实浏览器，让 MCP 客户端可以打开标签页、读取页面、填表、下载文件、投递视频，而不需要把账号密码交给模型。",
    "hero.download": "下载 Chrome 扩展",
    "hero.guide": "阅读 MCP 手册",
    "hero.register": "申请账号",
    "hero.note":
      "扩展尚未上架 Chrome Web Store，请从 GitHub Releases 下载 ZIP 后加载 unpacked extension。",
    "features.eyebrow": "能力",
    "features.title": "真实浏览器，<br class=\"zh-break\" />真实页面，真实操作",
    "features.lead": "浏览器工具由扩展在用户本机执行，服务端只负责路由、鉴权和审计。",
    "features.tabs.title": "标签与导航",
    "features.tabs.body": "创建、切换、更新、关闭标签页，打开 URL，读取当前页面信息。",
    "features.dom.title": "DOM 与交互",
    "features.dom.body": "查询元素、等待元素、点击、填表、键盘输入和文本提取。",
    "features.script.title": "脚本与网络",
    "features.script.body": "在页面主环境执行脚本，通过 CDP 拦截网络请求并读取响应。",
    "features.upload.title": "文件与上传",
    "features.upload.body": "单文件、多文件、URL 文件和本地路径文件上传，支持 base64 组装。",
    "features.video.title": "视频投递",
    "features.video.body": "接收 base64 或 URL 视频，暂存后注入页面文件输入框。",
    "features.account.title": "账号与审计",
    "features.account.body": "注册审批、API Key 限额、OAuth 登录、管理员操作和审计事件。",
    "install.eyebrow": "开始使用",
    "install.title": "三步接入",
    "install.lead": "从下载 ZIP 到接通浏览器，大约两分钟。",
    "install.step1.title": "安装扩展",
    "install.step1.body":
      "从 GitHub Releases 下载最新 ZIP，在 <code>chrome://extensions</code> 开启开发者模式并加载已解压的扩展。",
    "install.step2.title": "注册并创建 API Key",
    "install.step2.body":
      "登录控制台创建 API Key，把服务地址和 Key 填入扩展设置，点击连接。",
    "install.step3.title": "配置 MCP 客户端",
    "install.step3.body":
      "在 MCP 客户端中连接 <code>{issuer}/mcp</code> 并使用 OAuth 登录；授权页可以选择可操作的浏览器连接。",
    "install.download": "获取最新版本",
    "install.register": "创建账号",
    "install.cardTitle": "Chrome 加载步骤",
    "install.cardStep1": "解压下载的扩展 ZIP。",
    "install.cardStep2": "打开 <code>chrome://extensions</code>。",
    "install.cardStep3": "打开右上角“开发者模式”。",
    "install.cardStep4": "点击“加载已解压的扩展程序”，选择解压目录。",
    "install.cardStep5": "打开扩展选项，填写服务器地址与 API Key。",
    "mcp.eyebrow": "MCP 连接",
    "mcp.title": "OAuth 与浏览器策略",
    "mcp.lead":
      "MCP 客户端自动发现并完成浏览器登录；授权时可以选择固定一个浏览器，或指定一组浏览器连接。",
    "mcp.recommended": "推荐",
    "mcp.oauth.title": "OAuth 2.1 登录",
    "mcp.oauth.body":
      "客户端自动读取受保护资源元数据，动态注册并打开 ABM 登录页。授权后无需手动复制密钥。",
    "mcp.compatible": "隔离",
    "mcp.key.title": "浏览器任务会话",
    "mcp.key.body":
      "客户端可以固定到一个浏览器，也可以使用一组连接。每个任务获得服务端生成的 browserSessionId，避免并行任务互相干扰。",
    "mcp.resourceLabel": "资源",
    "mcp.metadataLabel": "元数据",
    "mcp.guide": "查看完整安装与工具手册",
    "cta.eyebrow": "准备就绪",
    "cta.title": "让 Agent 操作你的浏览器，<br class=\"zh-break\" />而不是你的密码",
    "cta.body":
      "扩展负责浏览器执行，服务端负责身份、权限和连接。两个仓库独立部署、独立升级。",
    "cta.download": "下载扩展",
    "cta.guide": "MCP 手册",
  },
};

initPageLanguage({
  translations,
  legacyStorageKeys: ["abm.landing.lang"],
});

const revealTargets = document.querySelectorAll(
  ".section-head, .feature-card, .connection-card, .install-steps, .install-card, .cta-inner",
);
if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && "IntersectionObserver" in window) {
  const revealObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
  );
  for (const target of revealTargets) {
    target.dataset.reveal = "";
    revealObserver.observe(target);
  }
}
