import { accountError, currentLanguage, initAccountPage, t } from "./account-i18n.js";
import { WORKFLOWS } from "./templates.js";
import {
  csrfToken,
  formatTime,
  logout,
  request,
  requireUser,
  showNotice,
} from "./api.js";

const keyList = document.getElementById("key-list");
const createForm = document.getElementById("create-key-form");
const newKeyBox = document.getElementById("new-key");
const newKeyValue = document.getElementById("new-key-value");
const passwordForm = document.getElementById("password-form");
const extensionId =
  document.querySelector("[data-extension-id]")?.dataset.extensionId || "";
const agentClient = document.getElementById("agent-client");
const agentConfig = document.getElementById("agent-config");
const extensionStatus = document.getElementById("extension-status");
const usageDays = document.getElementById("usage-days");
const usageToolCalls = document.getElementById("usage-tool-calls");
const usageVideoJobs = document.getElementById("usage-video-jobs");
const usageVideoBytes = document.getElementById("usage-video-bytes");
const usageByKey = document.getElementById("usage-by-key");
const usageQuotas = document.getElementById("usage-quotas");
const usageWarning = document.getElementById("usage-warning");
const sessionList = document.getElementById("session-list");
const identityList = document.getElementById("identity-list");
const identityProviders = document.getElementById("identity-providers");
const identityCount = document.getElementById("identity-count");
const templateGrid = document.getElementById("template-grid");
const accountNoticeList = document.getElementById("account-notice-list");
const noticeUnread = document.getElementById("notice-unread");
const emailStatus = document.getElementById("email-status");
const emailStatusAccount = document.getElementById("email-status-account");
const verifyEmailButton = document.getElementById("verify-email-button");
const consoleTabs = Array.from(document.querySelectorAll("[data-console-tab]"));
const consolePanels = Array.from(document.querySelectorAll("[data-console-panel]"));

const STATUS_KEYS = {
  active: "console.status.active",
  revoked: "console.status.revoked",
};

let currentUser;
let currentKeys = [];
let keysLoaded = false;
let keyOnline = new Map();
let extensionState = null;
let usageState = null;
let sessionsState = null;
let identitiesState = { items: [], providers: [] };
let noticesState = [];

initAccountPage({
  titleKey: "console.pageTitle",
  onChange() {
    if (currentUser) {
      renderAccount();
    }
    if (keysLoaded) {
      renderKeys();
    }
    renderExtensionStatus();
    renderUsage();
    renderSessions();
    renderIdentities();
    renderTemplates();
    renderNotices();
  },
});

function statusLabel(status) {
  return STATUS_KEYS[status] ? t(STATUS_KEYS[status]) : status;
}

function providerLabel(provider) {
  const key = `provider.${provider.id}`;
  const label = t(key);
  return label === key ? provider.name || provider.id : label;
}

function renderKey(key) {
  const row = document.createElement("div");
  row.className = "list-row";

  const info = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = key.name;
  const badge = document.createElement("span");
  badge.className = `status ${key.status}`;
  badge.textContent = statusLabel(key.status);
  title.append(" ", badge);
  if (keyOnline.has(key.id)) {
    const connection = document.createElement("span");
    const online = keyOnline.get(key.id);
    connection.className = `status ${online ? "online" : "offline"}`;
    connection.textContent = t(
      online ? "console.connectionOnline" : "console.connectionOffline",
    );
    title.append(" ", connection);
  }
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = t("console.keyMeta", {
    prefix: key.prefix,
    created: formatTime(key.createdAt),
    used: key.lastUsedAt ? formatTime(key.lastUsedAt) : t("console.never"),
  });
  info.append(title, meta);

  const actions = document.createElement("div");
  actions.className = "actions";
  const copy = document.createElement("button");
  copy.className = "button small";
  copy.type = "button";
  copy.textContent = t("console.copyPrefix");
  copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(key.prefix);
    showNotice(t("console.prefixCopied"));
  });
  actions.appendChild(copy);
  if (key.status === "active") {
    const revoke = document.createElement("button");
    revoke.className = "button small danger";
    revoke.type = "button";
    revoke.textContent = t("console.revoke");
    revoke.addEventListener("click", async () => {
      if (!window.confirm(t("console.revokeConfirm", { name: key.name }))) return;
      try {
        await request(`/api/v1/api-keys/${key.id}`, { method: "DELETE" });
        showNotice(t("console.revoked"));
        await refreshKeys();
      } catch (error) {
        showNotice(accountError(error), true);
      }
    });
    actions.appendChild(revoke);
  }

  row.append(info, actions);
  keyList.appendChild(row);
}

function renderKeys() {
  keyList.replaceChildren();
  const activeCount = currentKeys.filter((key) => key.status === "active").length;
  document.getElementById("key-count").textContent = t("console.keyCount", {
    count: activeCount,
  });
  if (currentKeys.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("console.noKeys");
    keyList.appendChild(empty);
    return;
  }
  currentKeys.forEach(renderKey);
}

async function refreshKeys() {
  currentKeys = await request("/api/v1/api-keys");
  keysLoaded = true;
  renderKeys();
  renderUsage();
}

function renderAccount() {
  document.getElementById("account-title").textContent = currentUser.displayName;
  document.getElementById("account-meta").textContent = t("console.accountMeta", {
    email: currentUser.email,
    joined: formatTime(currentUser.createdAt),
  });
  document.getElementById("plan-badge").textContent =
    currentUser.planCode === "pro" ? "Pro" : "Free";
  document.getElementById("admin-link").hidden = currentUser.role !== "admin";
  renderEmailStatus();
}

function renderEmailStatus() {
  if (!emailStatus) return;
  const verified = Boolean(currentUser?.emailVerifiedAt);
  const text = t(verified ? "console.emailVerified" : "console.emailUnverified");
  for (const element of [emailStatus, emailStatusAccount]) {
    if (!element) continue;
    element.textContent = text;
    element.className = `status ${verified ? "online" : "offline"}`;
  }
  if (verifyEmailButton) {
    verifyEmailButton.hidden = verified;
  }
}

async function sendEmailVerification() {
  if (!verifyEmailButton) return;
  verifyEmailButton.disabled = true;
  try {
    await request("/api/v1/auth/email-verification/request", {
      method: "POST",
    });
    showNotice(t("console.verificationSent"));
  } catch (error) {
    showNotice(accountError(error), true);
  } finally {
    verifyEmailButton.disabled = false;
  }
}

function mcpEndpoint() {
  return `${window.location.origin.replace(/\/+$/, "")}/mcp`;
}

function buildAgentConfig() {
  const endpoint = mcpEndpoint();
  switch (agentClient.value) {
    case "claude-code":
      return `claude mcp add --transport http abm ${endpoint}`;
    case "codex":
      return `codex mcp add abm --url ${endpoint}\ncodex mcp login abm`;
    case "cursor":
      return JSON.stringify(
        { mcpServers: { abm: { url: endpoint } } },
        null,
        2,
      );
    default:
      return JSON.stringify(
        { mcpServers: { abm: { type: "http", url: endpoint } } },
        null,
        2,
      );
  }
}

function renderAgentConfig() {
  if (agentConfig) {
    agentConfig.textContent = buildAgentConfig();
  }
}

function renderExtensionStatus() {
  if (!extensionStatus || !extensionState) return;
  const onlineCount = extensionState.connections.filter(
    (connection) => connection.online,
  ).length;
  extensionStatus.textContent = extensionState.connected
    ? t("console.extensionOnline", { count: onlineCount })
    : t("console.extensionOffline");
  extensionStatus.className = `status ${extensionState.connected ? "online" : "offline"}`;
}

async function refreshExtensionStatus() {
  if (!extensionStatus) return;
  extensionStatus.textContent = t("console.extensionChecking");
  extensionStatus.className = "status offline";
  try {
    const status = await request("/api/v1/extension/status");
    extensionState = status;
    keyOnline = new Map(
      (status.connections || []).map((connection) => [
        connection.id,
        Boolean(connection.online),
      ]),
    );
    renderExtensionStatus();
    if (keysLoaded) renderKeys();
  } catch {
    extensionState = { connected: false, connections: [] };
    keyOnline = new Map();
    renderExtensionStatus();
  }
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function renderQuotas() {
  if (!usageQuotas || !usageState?.quotas) return;
  const rows = [    ["toolCalls", "console.usageToolCalls", (value) => String(value)],
    ["videoJobs", "console.usageVideoJobs", (value) => String(value)],
    ["videoBytes", "console.usageVideoBytes", formatBytes],
  ];
  usageQuotas.replaceChildren();
  for (const [key, labelKey, format] of rows) {
    const quota = usageState.quotas[key];
    if (!quota) continue;
    const row = document.createElement("div");
    row.className = `quota-row${quota.over ? " over" : ""}`;
    const label = document.createElement("span");
    label.textContent = t(labelKey);
    const track = document.createElement("span");
    track.className = "quota-track";
    const fill = document.createElement("span");
    fill.className = "quota-fill";
    fill.style.width = `${Math.min(quota.percent, 100)}%`;
    track.appendChild(fill);
    const value = document.createElement("span");
    value.className = "quota-value";
    value.textContent =
      quota.limit > 0
        ? `${format(quota.used)} / ${format(quota.limit)}`
        : t("console.quotaUnlimited");
    row.append(label, track, value);
    usageQuotas.appendChild(row);
  }
  const over = Object.values(usageState.quotas).some((quota) => quota.over);
  if (usageWarning) {
    usageWarning.hidden = !over;
    usageWarning.textContent = over ? t("console.quotaWarning") : "";
  }
}

function renderTemplates() {
  if (!templateGrid) return;
  const language = currentLanguage() === "en" ? "en" : "zh";
  templateGrid.replaceChildren();
  for (const item of WORKFLOWS[language] || WORKFLOWS.en) {
    const card = document.createElement("article");
    card.className = "template-card";
    const title = document.createElement("h3");
    title.textContent = item.title;
    const description = document.createElement("p");
    description.textContent = item.description;
    const prompt = document.createElement("pre");
    prompt.textContent = item.prompt;
    const actions = document.createElement("div");
    actions.className = "actions";
    const copy = document.createElement("button");
    copy.className = "button small";
    copy.type = "button";
    copy.textContent = t("console.templateCopy");
    copy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(item.prompt);
      showNotice(t("console.templateCopied"));
    });
    actions.appendChild(copy);
    card.append(title, description, prompt, actions);
    templateGrid.appendChild(card);
  }
}

function renderUsage() {
  if (!usageState) return;
  usageToolCalls.textContent = String(usageState.totals.toolCalls);
  usageVideoJobs.textContent = String(usageState.totals.videoJobs);
  usageVideoBytes.textContent = formatBytes(usageState.totals.videoBytes);
  renderQuotas();
  const names = new Map(currentKeys.map((key) => [key.id, key.name]));
  usageByKey.replaceChildren();
  if (usageState.byKey.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("console.usageEmpty");
    usageByKey.appendChild(empty);
    return;
  }
  for (const item of usageState.byKey) {
    const row = document.createElement("div");
    row.className = "list-row";
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = names.get(item.apiKeyId) || item.apiKeyId;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = t("console.usageKeyMeta", {
      calls: item.toolCalls,
      jobs: item.videoJobs,
      bytes: formatBytes(item.videoBytes),
    });
    info.append(title, meta);
    row.appendChild(info);
    usageByKey.appendChild(row);
  }
}

async function refreshUsage() {
  if (!usageDays) return;
  try {
    const days = Number(usageDays.value) || 30;
    usageState = await request(`/api/v1/usage/summary?days=${days}`);
    renderUsage();
  } catch {
    usageState = {
      totals: { toolCalls: 0, videoJobs: 0, videoBytes: 0 },
      byKey: [],
    };
    renderUsage();
  }
}

function renderSessions() {
  if (!sessionList || !sessionsState) return;
  sessionList.replaceChildren();
  if (sessionsState.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("console.sessionsEmpty");
    sessionList.appendChild(empty);
    return;
  }
  for (const item of sessionsState) {
    const row = document.createElement("div");
    row.className = "list-row";
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.current
      ? t("console.sessionCurrent")
      : t("console.sessionOther");
    if (item.current) {
      const badge = document.createElement("span");
      badge.className = "status online";
      badge.textContent = t("console.sessionThisDevice");
      title.append(" ", badge);
    }
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = t("console.sessionMeta", {
      lastSeen: formatTime(item.lastSeenAt),
      expires: formatTime(item.expiresAt),
    });
    info.append(title, meta);
    row.appendChild(info);
    if (!item.current) {
      const actions = document.createElement("div");
      actions.className = "actions";
      const revoke = document.createElement("button");
      revoke.className = "button small danger";
      revoke.type = "button";
      revoke.textContent = t("console.revokeSession");
      revoke.addEventListener("click", () => void revokeSession(item.id));
      actions.appendChild(revoke);
      row.appendChild(actions);
    }
    sessionList.appendChild(row);
  }
}

async function refreshSessions() {
  if (!sessionList) return;
  try {
    const result = await request("/api/v1/auth/sessions");
    sessionsState = result.items || [];
    renderSessions();
  } catch {
    sessionsState = [];
    renderSessions();
  }
}

async function revokeSession(sessionId) {
  if (!window.confirm(t("console.revokeSessionConfirm"))) return;
  try {
    await request(`/api/v1/auth/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
    showNotice(t("console.sessionRevoked"));
    await refreshSessions();
  } catch (error) {
    showNotice(accountError(error), true);
  }
}

async function revokeOtherSessions() {
  if (!window.confirm(t("console.revokeOthersConfirm"))) return;
  try {
    await request("/api/v1/auth/sessions/revoke-others", { method: "POST" });
    showNotice(t("console.otherSessionsRevoked"));
    await refreshSessions();
  } catch (error) {
    showNotice(accountError(error), true);
  }
}

function providerMark(provider) {
  const mark = document.createElement("span");
  mark.className = `social-mark social-mark-${provider.id}`;
  mark.setAttribute("aria-hidden", "true");
  if (provider.id === "google") {
    mark.textContent = "G";
  } else if (provider.id === "github") {
    mark.textContent = "GH";
  } else if (provider.id === "wechat") {
    mark.textContent = "微";
  } else if (provider.id === "qq") {
    mark.textContent = "QQ";
  } else if (provider.id === "microsoft") {
    for (let index = 0; index < 4; index += 1) {
      mark.appendChild(document.createElement("span"));
    }
  } else {
    mark.textContent = (provider.name || provider.id).slice(0, 1);
  }
  return mark;
}

function renderIdentities() {
  if (!identityList) return;
  const items = identitiesState.items || [];
  const providers = identitiesState.providers || [];
  identityList.replaceChildren();
  if (identityCount) {
    identityCount.textContent = t("console.identityCount", { count: items.length });
  }
  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("console.identitiesEmpty");
    identityList.appendChild(empty);
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "list-row";
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = providerLabel({
      id: item.provider,
      name: item.providerName,
    });
    const badge = document.createElement("span");
    badge.className = `status ${
      item.emailVerified ? "online" : item.requiresEmail ? "offline" : "pending"
    }`;
    badge.textContent = item.emailVerified
      ? t("console.identityVerified")
      : item.requiresEmail
        ? t("console.identityNoEmail")
        : t("console.identityUnverified");
    title.append(" ", badge);
    const meta = document.createElement("div");
    meta.className = "meta";
    if (item.requiresEmail) {
      meta.textContent = t("console.identityMetaNoEmail", {
        linked: formatTime(item.linkedAt),
        lastLogin: item.lastLoginAt
          ? formatTime(item.lastLoginAt)
          : t("console.identityNever"),
      });
    } else {
      meta.textContent = t("console.identityMeta", {
        email: item.email,
        linked: formatTime(item.linkedAt),
        lastLogin: item.lastLoginAt
          ? formatTime(item.lastLoginAt)
          : t("console.identityNever"),
      });
    }
    info.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "actions";
    const unlink = document.createElement("button");
    unlink.className = "button small danger";
    unlink.type = "button";
    unlink.textContent = t("console.unlinkIdentity");
    unlink.addEventListener("click", () => void unlinkIdentity(item));
    actions.appendChild(unlink);
    row.append(info, actions);
    identityList.appendChild(row);
  }

  if (!identityProviders) return;
  identityProviders.replaceChildren();
  for (const provider of providers) {
    const link = document.createElement("a");
    link.className = "button social-button";
    link.href = `/api/v1/auth/social/${encodeURIComponent(provider.id)}/start?link=1&next=${encodeURIComponent("/console#account")}`;
    link.append(providerMark(provider));
    const label = document.createElement("span");
    label.textContent = t("console.linkProvider", {
      provider: providerLabel(provider),
    });
    link.appendChild(label);
    identityProviders.appendChild(link);
  }
  if (providers.length === 0) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = t("console.identitiesDisabled");
    identityProviders.appendChild(hint);
  }
}

async function refreshIdentities() {
  if (!identityList) return;
  try {
    identitiesState = await request("/api/v1/auth/identities");
    renderIdentities();
  } catch {
    identitiesState = { items: [], providers: [] };
    renderIdentities();
  }
}

async function unlinkIdentity(item) {
  const label = providerLabel({ id: item.provider, name: item.providerName });
  if (!window.confirm(t("console.unlinkConfirm", { provider: label }))) {
    return;
  }
  try {
    await request(`/api/v1/auth/identities/${encodeURIComponent(item.id)}`, {
      method: "DELETE",
    });
    showNotice(t("console.identityUnlinked"));
    await refreshIdentities();
  } catch (error) {
    showNotice(accountError(error), true);
  }
}

function renderNotices() {
  if (!accountNoticeList) return;
  accountNoticeList.replaceChildren();
  if (noticeUnread) {
    const unread = noticesState.filter((notice) => !notice.read).length;
    noticeUnread.textContent = t("console.noticeUnread", { count: unread });
  }
  if (noticesState.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("console.noticesEmpty");
    accountNoticeList.appendChild(empty);
    return;
  }
  for (const item of noticesState) {
    const row = document.createElement("div");
    row.className = `list-row${item.read ? "" : " unread"}`;
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.title;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = formatTime(item.createdAt);
    info.append(title, meta);
    if (item.body) {
      const body = document.createElement("div");
      body.className = "meta";
      body.textContent = item.body;
      info.appendChild(body);
    }
    const actions = document.createElement("div");
    actions.className = "actions";
    if (item.actionUrl) {
      const open = document.createElement("a");
      open.className = "button small";
      open.href = item.actionUrl;
      open.textContent = t("console.noticeOpen");
      actions.appendChild(open);
    }
    if (!item.read) {
      const read = document.createElement("button");
      read.className = "button small";
      read.type = "button";
      read.textContent = t("console.noticeRead");
      read.addEventListener("click", async () => {
        await request(`/api/v1/notices/${item.id}/read`, { method: "POST" });
        await refreshNotices();
      });
      actions.appendChild(read);
    }
    row.append(info, actions);
    accountNoticeList.appendChild(row);
  }
}

async function refreshNotices() {
  if (!accountNoticeList) return;
  try {
    const result = await request("/api/v1/notices?limit=20");
    noticesState = result.items || [];
    renderNotices();
  } catch {
    noticesState = [];
    renderNotices();
  }
}

async function deleteAccount() {
  const password = window.prompt(t("console.deleteAccountPrompt"));
  if (!password) return;
  if (!window.confirm(t("console.deleteAccountConfirm"))) return;
  try {
    await request("/api/v1/auth/account", {
      method: "DELETE",
      body: JSON.stringify({ password }),
    });
    window.location.assign("/");
  } catch (error) {
    showNotice(accountError(error), true);
  }
}

async function exportAccount() {
  try {
    const response = await fetch("/api/v1/auth/account/export", {
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "abm-account-export.json";
    link.click();
    URL.revokeObjectURL(url);
    showNotice(t("console.exportReady"));
  } catch (error) {
    showNotice(error?.message || t("console.exportFailed"), true);
  }
}

async function connectExtension() {
  const apiKey = newKeyBox.dataset.key;
  if (!apiKey) {
    showNotice(t("console.connectNoKey"), true);
    return;
  }
  if (!extensionId || !globalThis.chrome?.runtime?.sendMessage) {
    showNotice(t("console.connectUnavailable"), true);
    return;
  }
  try {
    const result = await chrome.runtime.sendMessage(extensionId, {
      type: "abm.connection.configure",
      payload: {
        serverBaseUrl: window.location.origin,
        apiKey,
      },
    });
    if (result?.ok) {
      showNotice(t("console.connectStarted"));
    } else {
      showNotice(result?.error || t("console.connectFailed"), true);
    }
  } catch (error) {
    showNotice(error?.message || t("console.connectFailed"), true);
  }
}

function activateConsoleTab(name, { updateHash = true } = {}) {
  const valid = consoleTabs.some((tab) => tab.dataset.consoleTab === name);
  const selected = valid ? name : "overview";
  for (const tab of consoleTabs) {
    const active = tab.dataset.consoleTab === selected;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of consolePanels) {
    panel.hidden = panel.dataset.consolePanel !== selected;
  }
  if (updateHash) {
    history.replaceState(null, "", `#${selected}`);
  }
}

async function init() {
  currentUser = await requireUser();
  if (!currentUser) return;
  renderAccount();
  renderTemplates();
  await refreshKeys();
  await Promise.all([
    refreshExtensionStatus(),
    refreshUsage(),
    refreshSessions(),
    refreshIdentities(),
    refreshNotices(),
  ]);
  window.setInterval(() => void refreshExtensionStatus(), 15000);
  window.setInterval(() => void refreshNotices(), 30000);
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = createForm.querySelector("button");
  const data = Object.fromEntries(new FormData(createForm));
  button.disabled = true;
  try {
    const result = await request("/api/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: data.name }),
    });
    createForm.reset();
    newKeyValue.textContent = result.plaintext;
    newKeyBox.hidden = false;
    newKeyBox.dataset.key = result.plaintext;
    showNotice(t("console.keyCreated"));
    await refreshKeys();
  } catch (error) {
    showNotice(accountError(error), true);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("copy-key-button").addEventListener("click", async () => {
  await navigator.clipboard.writeText(newKeyBox.dataset.key);
  showNotice(t("console.keyCopied"));
});

document
  .getElementById("connect-extension-button")
  .addEventListener("click", connectExtension);

document
  .getElementById("refresh-extension-status")
  .addEventListener("click", () => void refreshExtensionStatus());

if (usageDays) {
  usageDays.addEventListener("change", () => void refreshUsage());
}

document
  .getElementById("revoke-other-sessions")
  .addEventListener("click", () => void revokeOtherSessions());

if (verifyEmailButton) {
  verifyEmailButton.addEventListener("click", () => void sendEmailVerification());
}

document
  .getElementById("read-all-notices")
  .addEventListener("click", async () => {
    await request("/api/v1/notices/read-all", { method: "POST" });
    await refreshNotices();
  });

document
  .getElementById("delete-account-button")
  .addEventListener("click", () => void deleteAccount());

document
  .getElementById("export-account-button")
  .addEventListener("click", () => void exportAccount());

if (agentClient) {
  agentClient.addEventListener("change", renderAgentConfig);
  renderAgentConfig();
}

document
  .getElementById("copy-agent-config")
  .addEventListener("click", async () => {
    await navigator.clipboard.writeText(agentConfig.textContent || "");
    showNotice(t("console.agentCopied"));
  });

passwordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = passwordForm.querySelector("button");
  const data = Object.fromEntries(new FormData(passwordForm));
  button.disabled = true;
  try {
    await request("/api/v1/auth/password", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    passwordForm.reset();
    showNotice(t("console.passwordUpdated"));
  } catch (error) {
    showNotice(
      accountError(error, {
        ABM_INVALID_CREDENTIALS: "console.currentPasswordIncorrect",
      }),
      true,
    );
  } finally {
    button.disabled = false;
  }
});

document.getElementById("logout-button").addEventListener("click", logout);

for (const tab of consoleTabs) {
  tab.addEventListener("click", () => {
    activateConsoleTab(tab.dataset.consoleTab);
  });
}
activateConsoleTab(window.location.hash.slice(1), { updateHash: false });

const socialState = new URLSearchParams(window.location.search).get("social");
if (socialState === "linked") {
  showNotice(t("console.socialLinked"));
}
if (socialState === "login") {
  showNotice(t("console.socialLogin"));
}

init().catch(async (error) => {
  if (error.status === 401 && csrfToken()) {
    window.location.assign("/login");
    return;
  }
  showNotice(accountError(error), true);
});
