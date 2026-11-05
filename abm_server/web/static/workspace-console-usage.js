import { request } from "./api.js";
import { formatBytes, formatNumber, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const state = { days: 30, keys: [] };

function quotaRow(label, quota, format) {
  if (!quota) return "";
  const percent = quota.limit ? Math.min(100, Math.round((quota.used / quota.limit) * 100)) : 0;
  const value = quota.limit ? `${format(quota.used)} / ${format(quota.limit)}` : `${format(quota.used)} / ∞`;
  const cls = quota.over ? "bad" : percent >= 80 ? "warn" : "";
  return `<div class="ws-quota-row"><span>${label}</span><b>${value}</b></div><div class="ws-track"><i class="${cls}" style="width:${percent}%"></i></div>`;
}

function render(usage) {
  const totals = usage.totals || {};
  const quotas = usage.quotas || {};
  setText("wsUsageCalls", formatNumber(totals.toolCalls || 0));
  setText("wsUsageJobs", formatNumber(totals.videoJobs || 0));
  setText("wsUsageBytes", formatBytes(totals.videoBytes || 0));
  setText("wsUsagePlan", usage.plan === "pro" ? "Pro" : "Free");
  setText("wsUsageCallsMeta", quotas.toolCalls ? `${formatNumber(quotas.toolCalls.used)} / ${formatNumber(quotas.toolCalls.limit)}` : "—");
  setText("wsUsageJobsMeta", quotas.videoJobs ? `${formatNumber(quotas.videoJobs.used)} / ${formatNumber(quotas.videoJobs.limit)}` : "—");
  setText("wsUsageBytesMeta", quotas.videoBytes ? `${formatBytes(quotas.videoBytes.used)} / ${formatBytes(quotas.videoBytes.limit)}` : "—");
  setText("wsUsagePlanMeta", t("workspace.daysWindow", { days: state.days }));
  setText("wsUsageReset", t("workspace.daysWindow", { days: state.days }));

  $("wsUsageQuotas").innerHTML =
    quotaRow(t("workspace.metricCalls"), quotas.toolCalls, formatNumber) +
    quotaRow(t("workspace.videoJobs"), quotas.videoJobs, formatNumber) +
    quotaRow(t("workspace.videoBytes"), quotas.videoBytes, formatBytes) ||
    `<div class="ws-empty">${t("workspace.noQuota")}</div>`;

  const names = new Map(state.keys.map((key) => [key.id, key.name]));
  $("wsUsageByKey").innerHTML = (usage.byKey || []).length
    ? usage.byKey
        .map(
          (item) => `<tr><td><b>${escapeHtml(names.get(item.apiKeyId) || item.apiKeyId)}</b></td><td>${formatNumber(item.toolCalls)}</td><td>${formatNumber(item.videoJobs)}</td><td>${formatBytes(item.videoBytes)}</td></tr>`,
        )
        .join("")
    : `<tr><td colspan="4"><div class="ws-empty">${t("workspace.noUsage")}</div></td></tr>`;

  const warnings = Object.entries(quotas).filter(([, quota]) => quota.over || quota.percent >= 80);
  const quotaLabels = {
    toolCalls: t("workspace.metricCalls"),
    videoJobs: t("workspace.videoJobs"),
    videoBytes: t("workspace.videoBytes"),
  };
  $("wsUsageWarnings").innerHTML = warnings.length
    ? warnings
        .map(
          ([key, quota]) =>
            `<div class="ws-notice ${quota.over ? "error" : ""}" style="margin-bottom:8px"><span>${escapeHtml(t("workspace.quotaWarning", { name: quotaLabels[key] || key, percent: Math.round(quota.percent) }))}</span></div>`,
        )
        .join("")
    : `<div class="ws-notice info"><span>${t("workspace.quotaHealthy")}</span></div>`;
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function load() {
  try {
    const [usage, keys] = await Promise.all([
      request(`/api/v1/usage/summary?days=${state.days}`),
      request("/api/v1/api-keys"),
    ]);
    state.keys = keys || [];
    render(usage);
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

$("wsUsagePeriod").addEventListener("click", (event) => {
  const button = event.target.closest("[data-days]");
  if (!button) return;
  state.days = Number(button.dataset.days) || 30;
  document.querySelectorAll("#wsUsagePeriod button").forEach((item) => {
    item.classList.toggle("on", item === button);
  });
  load();
});

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", load);
});
