import { formatTime, request } from "./api.js";
import { closeDrawer, confirmAction, escapeHtml, openDrawer, toast } from "./ui.js";
import {
  debounce,
  formatDate,
  planLabel,
  refreshAdminBadge,
  renderPagination,
  statusClass,
  statusLabel,
} from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const PAGE_SIZE = 20;
const state = { page: 1, total: 0, query: "", status: "", plan: "", items: [] };

const $ = (id) => document.getElementById(id);

function statusBadge(status) {
  return `<span class="ws-status ${statusClass(status)}">${escapeHtml(statusLabel(status))}</span>`;
}

function usageText(usage) {
  if (!usage) return "—";
  const calls = Number(usage.toolCalls || 0).toLocaleString();
  const jobs = Number(usage.videoJobs || 0).toLocaleString();
  return `${calls} 次 · ${jobs} 个视频`;
}

function row(user) {
  return `
    <tr data-user-id="${user.id}">
      <td><div class="ws-user-cell"><span class="ws-avatar">${escapeHtml((user.displayName || "U").slice(0, 1))}</span><span><b>${escapeHtml(user.displayName)}</b><small>${escapeHtml(user.email)}</small></span></div></td>
      <td>${statusBadge(user.status)}</td>
      <td><span class="ws-pill">${escapeHtml(planLabel(user.planCode))}</span></td>
      <td>${usageText(user.usage)}</td>
      <td>${escapeHtml(formatDate(user.createdAt))}</td>
      <td class="ws-actions-cell"><button class="ws-btn ws-btn-small" type="button" data-open-user="${user.id}">${escapeHtml(t("workspace.open"))}</button></td>
    </tr>`;
}

function render() {
  const body = $("wsUsersBody");
  if (!state.items.length) {
    body.innerHTML = `<tr><td colspan="6"><div class="ws-empty">${escapeHtml(t("workspace.noUsers"))}</div></td></tr>`;
  } else {
    body.innerHTML = state.items.map(row).join("");
    body.querySelectorAll("[data-open-user]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const user = state.items.find((item) => item.id === button.dataset.openUser);
        if (user) openUser(user);
      });
    });
    body.querySelectorAll("tr[data-user-id]").forEach((rowElement) => {
      rowElement.addEventListener("click", () => {
        const user = state.items.find((item) => item.id === rowElement.dataset.userId);
        if (user) openUser(user);
      });
    });
  }
  const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  $("wsUsersPageInfo").textContent = `${state.page} / ${pages} · ${t("workspace.totalUsers", { count: state.total })}`;
  renderPagination($("wsUsersPager"), state.page, state.total, PAGE_SIZE, (page) => {
    state.page = page;
    load();
  });
}

async function load() {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((state.page - 1) * PAGE_SIZE),
  });
  if (state.query) params.set("q", state.query);
  if (state.status) params.set("status", state.status);
  if (state.plan) params.set("plan", state.plan);
  $("wsUsersBody").innerHTML = `<tr><td colspan="6"><div class="ws-empty">${escapeHtml(t("workspace.loading"))}</div></td></tr>`;
  try {
    const result = await request(`/api/v1/admin/users?${params}`);
    state.items = result.items || [];
    state.total = Number(result.total || 0);
    const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    if (state.page > pages) {
      state.page = pages;
      return load();
    }
    $("wsUserCount").textContent = `${t("workspace.totalUsers", { count: state.total })}`;
    render();
    refreshAdminBadge();
  } catch {
    $("wsUsersBody").innerHTML = `<tr><td colspan="6"><div class="ws-empty">${escapeHtml(t("workspace.loadFailed"))}</div></td></tr>`;
    toast(t("workspace.loadFailed"), true);
  }
}

function deviceLabel(userAgent) {
  if (!userAgent) return "—";
  const browser = /Edg\//.test(userAgent)
    ? "Edge"
    : /Firefox\//.test(userAgent)
      ? "Firefox"
      : /Chrome\//.test(userAgent)
        ? "Chrome"
        : /Safari\//.test(userAgent)
          ? "Safari"
          : "Browser";
  const system = /Windows/.test(userAgent)
    ? "Windows"
    : /Mac OS X/.test(userAgent)
      ? "macOS"
      : /Android/.test(userAgent)
        ? "Android"
        : /iPhone|iPad/.test(userAgent)
          ? "iOS"
          : "Desktop";
  return `${browser} · ${system}`;
}

function loginHistory(sessions) {
  if (!sessions.length) {
    return `<div class="ws-empty">${escapeHtml(t("workspace.loginHistoryEmpty"))}</div>`;
  }
  return `<div class="ws-list">${sessions
    .map(
      (session) => `<div class="ws-list-row">
        <span><b>${escapeHtml(deviceLabel(session.userAgent))}</b><small>${escapeHtml(session.ipAddress || "—")}</small></span>
        <span class="right"><small>${escapeHtml(formatDate(session.lastSeenAt))}</small></span>
      </div>`,
    )
    .join("")}</div>`;
}

async function openUser(user) {
  let sessions = [];
  try {
    const detail = await request(`/api/v1/admin/users/${user.id}`);
    sessions = detail.sessions || [];
  } catch {
    sessions = [];
  }
  const formId = `user-form-${user.id}`;
  const expiry = user.planExpiresAt ? user.planExpiresAt.slice(0, 16) : "";
  openDrawer({
    title: user.displayName,
    sub: `${user.email} · ${t("workspace.joinedColumn")} ${formatDate(user.createdAt)}`,
    body: `
      <div class="ws-metrics" style="grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px">
        <div class="ws-metric" style="padding: 10px"><span>${escapeHtml(t("workspace.metricCalls"))}</span><b style="font-size: 20px">${Number(user.usage?.toolCalls || 0).toLocaleString()}</b></div>
        <div class="ws-metric" style="padding: 10px"><span>${escapeHtml(t("workspace.videoJobs"))}</span><b style="font-size: 20px">${Number(user.usage?.videoJobs || 0).toLocaleString()}</b></div>
        <div class="ws-metric" style="padding: 10px"><span>${escapeHtml(t("workspace.videoBytes"))}</span><b style="font-size: 20px">${Number(user.usage?.videoBytes || 0) ? (Number(user.usage.videoBytes) / 1024 / 1024 / 1024).toFixed(2) + " GB" : "0 B"}</b></div>
        <div class="ws-metric" style="padding: 10px"><span>${escapeHtml(t("workspace.planColumn"))}</span><b style="font-size: 20px">${escapeHtml(planLabel(user.planCode))}</b></div>
      </div>
      <div class="ws-drawer-section"><h3>${escapeHtml(t("workspace.profile"))}</h3>
        <dl class="ws-kv">
          <dt>${escapeHtml(t("workspace.email"))}</dt><dd>${escapeHtml(user.email)}</dd>
          <dt>${escapeHtml(t("workspace.emailStatus"))}</dt><dd>${user.emailVerifiedAt ? escapeHtml(t("workspace.emailVerified")) : escapeHtml(t("workspace.emailUnverified"))}</dd>
          <dt>${escapeHtml(t("workspace.applicationNote"))}</dt><dd>${escapeHtml(user.applicationNote || "—")}</dd>
          <dt>${escapeHtml(t("workspace.statusReason"))}</dt><dd>${escapeHtml(user.statusReason || "—")}</dd>
          <dt>${escapeHtml(t("workspace.approvedAt"))}</dt><dd>${user.approvedAt ? escapeHtml(formatTime(user.approvedAt)) : "—"}</dd>
        </dl>
      </div>
      <div class="ws-drawer-section"><h3>${escapeHtml(t("workspace.loginHistory"))}</h3>
        ${loginHistory(sessions)}
      </div>
      <div class="ws-drawer-section"><h3>${escapeHtml(t("workspace.manageUser"))}</h3>
        <div class="ws-form-grid" id="${formId}">
          <label class="ws-field">${escapeHtml(t("workspace.statusColumn"))}<select class="ws-select" id="udStatus"><option value="pending" ${user.status === "pending" ? "selected" : ""}>${escapeHtml(statusLabel("pending"))}</option><option value="active" ${user.status === "active" ? "selected" : ""}>${escapeHtml(statusLabel("active"))}</option><option value="disabled" ${user.status === "disabled" ? "selected" : ""}>${escapeHtml(statusLabel("disabled"))}</option><option value="rejected" ${user.status === "rejected" ? "selected" : ""}>${escapeHtml(statusLabel("rejected"))}</option></select></label>
          <label class="ws-field">${escapeHtml(t("workspace.planColumn"))}<select class="ws-select" id="udPlan"><option value="free" ${user.planCode === "free" ? "selected" : ""}>Free</option><option value="pro" ${user.planCode === "pro" ? "selected" : ""}>Pro</option></select></label>
          <label class="ws-field" style="grid-column: 1 / -1">${escapeHtml(t("workspace.planExpires"))}<input class="ws-input" id="udExpiry" type="datetime-local" value="${escapeHtml(expiry)}" /></label>
          <label class="ws-field" style="grid-column: 1 / -1">${escapeHtml(t("workspace.statusReason"))}<input class="ws-input" id="udReason" value="${escapeHtml(user.statusReason || "")}" placeholder="${escapeHtml(t("workspace.optional"))}" /></label>
        </div>
      </div>`,
    footer: `
      <button class="ws-btn ws-btn-small" type="button" data-drawer-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
      ${user.status === "pending" ? `<button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-drawer-action="reject">${escapeHtml(t("workspace.reject"))}</button>` : ""}
      ${user.status === "active" ? `<button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-drawer-action="disable">${escapeHtml(t("workspace.disable"))}</button>` : ""}
      ${user.status === "pending" ? `<button class="ws-btn ws-btn-small ws-btn-primary" type="button" data-drawer-action="approve">${escapeHtml(t("workspace.approve"))}</button>` : ""}
      ${user.status === "disabled" || user.status === "rejected" ? `<button class="ws-btn ws-btn-small ws-btn-primary" type="button" data-drawer-action="enable">${escapeHtml(t("workspace.enable"))}</button>` : ""}
      <button class="ws-btn ws-btn-small ws-btn-primary" type="button" data-drawer-action="save">${escapeHtml(t("workspace.save"))}</button>`,
    onAction: (action) => {
      if (action === "cancel") return closeDrawer();
      if (action === "approve") return patchUser(user, { status: "active" });
      if (action === "enable") return patchUser(user, { status: "active" });
      if (action === "reject") {
        return confirmAction(t("workspace.rejectTitle"), t("workspace.rejectBody", { name: user.displayName }), () => patchUser(user, { status: "rejected" }));
      }
      if (action === "disable") {
        return confirmAction(t("workspace.disableTitle"), t("workspace.disableBody", { name: user.displayName }), () => patchUser(user, { status: "disabled" }));
      }
      if (action === "save") {
        const status = document.getElementById("udStatus").value;
        const plan = document.getElementById("udPlan").value;
        const expiry = document.getElementById("udExpiry").value;
        const reason = document.getElementById("udReason").value.trim();
        return patchUser(user, {
          status,
          plan_code: plan,
          plan_expires_at: expiry ? new Date(expiry).toISOString() : null,
          reason,
        });
      }
    },
  });
}

async function patchUser(user, payload) {
  try {
    await request(`/api/v1/admin/users/${user.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    closeDrawer();
    toast(t("workspace.userUpdated", { name: user.displayName }));
    await load();
    refreshAdminBadge();
  } catch {
    toast(t("workspace.updateFailed"), true);
  }
}

async function exportCsv() {
  try {
    const result = await request("/api/v1/admin/users?limit=500&offset=0");
    const rows = [
      ["email", "display_name", "status", "plan", "created_at"],
      ...(result.items || []).map((user) => [
        user.email,
        user.displayName,
        user.status,
        user.planCode,
        user.createdAt,
      ]),
    ];
    const csv = rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "abm-users.csv";
    link.click();
    URL.revokeObjectURL(url);
    toast(t("workspace.exported"));
  } catch {
    toast(t("workspace.exportFailed"), true);
  }
}

const debouncedSearch = debounce(() => {
  state.page = 1;
  load();
});

$("wsUserSearch").addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  debouncedSearch();
});
$("wsUserStatus").addEventListener("change", (event) => {
  state.status = event.target.value;
  state.page = 1;
  load();
});
$("wsUserPlan").addEventListener("change", (event) => {
  state.plan = event.target.value;
  state.page = 1;
  load();
});
$("wsExportUsers").addEventListener("click", exportCsv);

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", () => load());
});
