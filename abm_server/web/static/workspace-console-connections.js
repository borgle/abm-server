import { formatTime, request } from "./api.js";
import { confirmAction, escapeHtml, openModal, closeModal, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const state = { keys: [], connections: [], agent: "claude" };

function keyRow(key) {
  const online = state.connections.find((item) => item.id === key.id)?.online;
  const status =
    key.status === "revoked"
      ? `<span class="ws-status ws-status-bad">${escapeHtml(t("workspace.revoked"))}</span>`
      : online
        ? `<span class="ws-status ws-status-ok">${escapeHtml(t("workspace.connected"))}</span>`
        : `<span class="ws-status ws-status-warn">${escapeHtml(t("workspace.offline"))}</span>`;
  return `
    <tr>
      <td><b>${escapeHtml(key.name)}</b></td>
      <td>${status}</td>
      <td class="ws-key-prefix">${escapeHtml(key.prefix)}</td>
      <td>${key.lastUsedAt ? escapeHtml(formatTime(key.lastUsedAt)) : escapeHtml(t("workspace.never"))}</td>
      <td class="ws-actions-cell">
        <button class="ws-btn ws-btn-small" type="button" data-copy="${escapeHtml(key.prefix)}">${escapeHtml(t("workspace.copy"))}</button>
        ${key.status === "active" ? `<button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-revoke="${key.id}">${escapeHtml(t("workspace.revoke"))}</button>` : ""}
      </td>
    </tr>`;
}

function renderKeys() {
  const active = state.keys.filter((key) => key.status === "active").length;
  $("wsKeySummary").textContent = t("workspace.keysSummary", { active, total: state.keys.length });
  const online = state.keys.some((key) => state.connections.find((item) => item.id === key.id)?.online);
  $("wsKeyOnlineStatus").textContent = online ? t("workspace.connected") : t("workspace.offline");
  $("wsKeyOnlineStatus").className = `ws-status ${online ? "ws-status-ok" : "ws-status-warn"}`;
  const body = $("wsKeysBody");
  if (!state.keys.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="ws-empty">${escapeHtml(t("workspace.noKeys"))}</div></td></tr>`;
    return;
  }
  body.innerHTML = state.keys.map(keyRow).join("");
  body.querySelectorAll("[data-revoke]").forEach((button) => {
    button.addEventListener("click", () => revokeKey(button.dataset.revoke));
  });
  body.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      navigator.clipboard?.writeText(button.dataset.copy).catch(() => {});
      toast(t("workspace.copied"));
    });
  });
}

function renderExtension() {
  const online = state.connections.filter((item) => item.online).length;
  $("wsExtensionBadge").textContent = online ? t("workspace.connected") : t("workspace.offline");
  $("wsExtensionBadge").className = `ws-status ${online ? "ws-status-ok" : "ws-status-warn"}`;
  const list = $("wsExtensionList");
  if (!state.connections.length) {
    list.innerHTML = `<div class="ws-empty">${escapeHtml(t("workspace.noExtension"))}</div>`;
    return;
  }
  list.innerHTML = state.connections
    .map(
      (item) => `<div class="ws-list-row">
        <span class="ws-dot ${item.online ? "ws-dot-on" : ""}"></span>
        <span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.online ? t("workspace.connected") : t("workspace.offline"))}${item.extensionVersion ? " · v" + escapeHtml(item.extensionVersion) : ""}</small></span>
        <span class="right"><span class="ws-pill">${escapeHtml(item.prefix)}</span></span>
      </div>`,
    )
    .join("");
}

function agentCode(client) {
  const endpoint = `${window.location.origin.replace(/\/+$/, "")}/mcp`;
  if (client === "claude") return `claude mcp add --transport http abm ${endpoint}`;
  if (client === "codex") return `codex mcp add abm --url ${endpoint}\ncodex mcp login abm`;
  if (client === "cursor")
    return JSON.stringify({ mcpServers: { abm: { url: endpoint } } }, null, 2);
  return JSON.stringify({ mcpServers: { abm: { type: "http", url: endpoint } } }, null, 2);
}

function renderAgent() {
  $("wsAgentCode").textContent = agentCode(state.agent);
  document.querySelectorAll("#wsAgentTabs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.agent === state.agent);
  });
}

async function load() {
  try {
    const [keys, extension] = await Promise.all([
      request("/api/v1/api-keys"),
      request("/api/v1/extension/status"),
    ]);
    state.keys = keys || [];
    state.connections = extension.connections || [];
    renderKeys();
    renderExtension();
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

function openCreateKey() {
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.createKey"))}</h2>
      <p>${escapeHtml(t("workspace.createKeyLead"))}</p>
      <label class="ws-field">${escapeHtml(t("workspace.keyName"))}<input class="ws-input" id="wsNewKeyName" placeholder="${escapeHtml(t("workspace.keyNamePlaceholder"))}" /></label>
      <div class="ws-actions" style="justify-content:flex-end;margin-top:14px">
        <button class="ws-btn" type="button" data-modal-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" id="wsCreateKeyConfirm">${escapeHtml(t("workspace.create"))}</button>
      </div>
    </div>`,
    t("workspace.createKey"),
  );
  modal.onclick = (event) => {
    if (event.target.closest('[data-modal-action="cancel"]')) closeModal();
  };
  $("wsCreateKeyConfirm").addEventListener("click", async () => {
    const name = $("wsNewKeyName").value.trim();
    if (!name) return toast(t("workspace.keyNameRequired"), true);
    try {
      const result = await request("/api/v1/api-keys", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      closeModal();
      showSecret(result);
      await load();
    } catch {
      toast(t("workspace.createKeyFailed"), true);
    }
  });
}

function showSecret(key) {
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.saveKey"))}</h2>
      <p>${escapeHtml(t("workspace.saveKeyLead"))}</p>
      <div class="ws-code">${escapeHtml(key.plaintext)}</div>
      <div class="ws-actions" style="justify-content:flex-end;margin-top:14px">
        <button class="ws-btn" type="button" id="wsCopySecret">${escapeHtml(t("workspace.copy"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" data-modal-action="close">${escapeHtml(t("workspace.saved"))}</button>
      </div>
    </div>`,
    t("workspace.saveKey"),
  );
  modal.onclick = (event) => {
    if (event.target.closest('[data-modal-action="close"]')) closeModal();
  };
  $("wsCopySecret").addEventListener("click", () => {
    navigator.clipboard?.writeText(key.plaintext).catch(() => {});
    toast(t("workspace.copied"));
  });
}

function revokeKey(keyId) {
  const key = state.keys.find((item) => item.id === keyId);
  confirmAction(
    t("workspace.revokeKeyTitle"),
    t("workspace.revokeKeyBody", { name: key?.name || "" }),
    async () => {
      try {
        await request(`/api/v1/api-keys/${keyId}`, { method: "DELETE" });
        toast(t("workspace.keyRevoked"));
        await load();
      } catch {
        toast(t("workspace.revokeKeyFailed"), true);
      }
    },
  );
}

$("wsCreateKey").addEventListener("click", openCreateKey);
$("wsRefreshExtension").addEventListener("click", load);
$("wsAgentTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-agent]");
  if (!button) return;
  state.agent = button.dataset.agent;
  renderAgent();
});
$("wsCopyAgent").addEventListener("click", () => {
  navigator.clipboard?.writeText(agentCode(state.agent)).catch(() => {});
  toast(t("workspace.copied"));
});

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  renderAgent();
  window.addEventListener("workspace:language", () => {
    load();
    renderAgent();
  });
});
