import { request } from "./api.js";
import { escapeHtml, openDrawer, toast } from "./ui.js";
import {
  eventLabel,
  formatDate,
  refreshAdminBadge,
  renderPagination,
} from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const PAGE_SIZE = 20;
const state = { page: 1, total: 0, event: "", days: 30, items: [] };
const $ = (id) => document.getElementById(id);

const FIELD_LABELS = {
  status: "workspace.statusColumn",
  reason: "workspace.statusReason",
  planCode: "workspace.planColumn",
  planExpiresAt: "workspace.planExpires",
  registrationRequireApproval: "workspace.metricApproval",
  model: "workspace.modelLabel",
};

function isSensitive(field) {
  return /(password|secret|token|key|cookie)/i.test(field);
}

function summarize(event) {
  const changes = event.metadata?.changes || {};
  const keys = Object.keys(changes);
  if (!keys.length) return "—";
  return keys
    .slice(0, 2)
    .map((key) => {
      const change = changes[key] || {};
      return `${t(FIELD_LABELS[key] || key)}: ${String(change.before ?? "—")} → ${String(change.after ?? "—")}`;
    })
    .join(" · ");
}

function render() {
  const body = $("wsAuditBody");
  if (!state.items.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="ws-empty">${escapeHtml(t("workspace.noAudit"))}</div></td></tr>`;
  } else {
    body.innerHTML = state.items
      .map(
        (event) => `<tr data-audit-id="${event.id}">
          <td>${escapeHtml(formatDate(event.createdAt))}</td>
          <td><b>${escapeHtml(eventLabel(event.eventType))}</b></td>
          <td>${escapeHtml(event.actorName || event.actorUserId || "—")}</td>
          <td>${escapeHtml(event.subjectName || event.subjectUserId || "—")}</td>
          <td class="ws-muted-cell">${escapeHtml(summarize(event))}</td>
        </tr>`,
      )
      .join("");
    body.querySelectorAll("tr[data-audit-id]").forEach((row) => {
      row.addEventListener("click", () => {
        const event = state.items.find((item) => item.id === row.dataset.auditId);
        if (event) openAudit(event);
      });
    });
  }
  const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  $("wsAuditPageInfo").textContent = `${state.page} / ${pages} · ${t("workspace.totalEvents", { count: state.total })}`;
  renderPagination($("wsAuditPager"), state.page, state.total, PAGE_SIZE, (page) => {
    state.page = page;
    load();
  });
}

async function load() {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((state.page - 1) * PAGE_SIZE),
    from: new Date(Date.now() - state.days * 24 * 60 * 60 * 1000).toISOString(),
  });
  if (state.event) params.set("event_type", state.event);
  $("wsAuditBody").innerHTML = `<tr><td colspan="5"><div class="ws-empty">${escapeHtml(t("workspace.loading"))}</div></td></tr>`;
  try {
    const result = await request(`/api/v1/admin/audit?${params}`);
    state.items = result.items || [];
    state.total = Number(result.total || 0);
    $("wsAuditCount").textContent = t("workspace.totalEvents", { count: state.total });
    render();
    refreshAdminBadge();
  } catch {
    $("wsAuditBody").innerHTML = `<tr><td colspan="5"><div class="ws-empty">${escapeHtml(t("workspace.loadFailed"))}</div></td></tr>`;
    toast(t("workspace.loadFailed"), true);
  }
}

function openAudit(event) {
  const changes = event.metadata?.changes || {};
  const keys = Object.keys(changes);
  const rows = keys
    .map((key) => {
      const change = changes[key] || {};
      const before = isSensitive(key) ? "***" : change.before ?? "—";
      const after = isSensitive(key) ? "***" : change.after ?? "—";
      return `<tr><td><b>${escapeHtml(t(FIELD_LABELS[key] || key))}</b></td><td class="old">${escapeHtml(String(before))}</td><td class="new">${escapeHtml(String(after))}</td></tr>`;
    })
    .join("");
  const diff = keys.length
    ? `<table class="ws-diff"><thead><tr><th>${escapeHtml(t("workspace.field"))}</th><th>${escapeHtml(t("workspace.before"))}</th><th>${escapeHtml(t("workspace.after"))}</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="ws-empty">${escapeHtml(t("workspace.noDiff"))}</div>`;
  openDrawer({
    title: eventLabel(event.eventType),
    sub: `${formatDate(event.createdAt)} · ${event.actorName || event.actorUserId || "—"} → ${event.subjectName || event.subjectUserId || "—"}`,
    body: `${diff}<div class="ws-drawer-section"><h3>${escapeHtml(t("workspace.rawMetadata"))}</h3><div class="ws-code">${escapeHtml(JSON.stringify(event.metadata || {}, null, 2))}</div></div>`,
  });
}

async function exportCsv() {
  try {
    const result = await request("/api/v1/admin/audit?limit=500&offset=0&from=" + encodeURIComponent(new Date(Date.now() - state.days * 24 * 60 * 60 * 1000).toISOString()));
    const rows = [
      ["created_at", "event_type", "actor", "subject", "metadata"],
      ...(result.items || []).map((event) => [
        event.createdAt,
        event.eventType,
        event.actorName || event.actorUserId,
        event.subjectName || event.subjectUserId,
        JSON.stringify(event.metadata || {}),
      ]),
    ];
    const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "abm-audit.csv";
    link.click();
    URL.revokeObjectURL(url);
    toast(t("workspace.exported"));
  } catch {
    toast(t("workspace.exportFailed"), true);
  }
}

$("wsAuditEvent").addEventListener("change", (event) => {
  state.event = event.target.value;
  state.page = 1;
  load();
});
$("wsAuditRange").addEventListener("change", (event) => {
  state.days = Number(event.target.value) || 30;
  state.page = 1;
  load();
});
$("wsExportAudit").addEventListener("click", exportCsv);

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", () => load());
});
