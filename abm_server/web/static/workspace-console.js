import { request } from "./api.js";
import { formatBytes, formatNumber, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function planLabel(plan) {
  return plan === "pro" ? t("workspace.planPro") : t("workspace.planFree");
}

function quotaText(quota, formatter = formatNumber) {
  if (!quota) return "—";
  if (!quota.limit) return `${formatter(quota.used)} / ∞`;
  return `${formatter(quota.used)} / ${formatter(quota.limit)}`;
}

function quotaPercent(quota) {
  if (!quota || !quota.limit) return 0;
  return Math.min(100, Math.round((quota.used / quota.limit) * 100));
}

async function refresh(user) {
  const [keysResult, extensionResult, usageResult] = await Promise.allSettled([
    request("/api/v1/api-keys"),
    request("/api/v1/extension/status"),
    request("/api/v1/usage/summary?days=30"),
  ]);

  setText("wsPlan", planLabel(user.planCode));
  setText(
    "wsPlanMeta",
    user.planExpiresAt
      ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(user.planExpiresAt))
      : user.planCode === "pro"
        ? t("workspace.planPro")
        : t("workspace.planFree"),
  );
  setText("wsEmail", user.email);
  setText(
    "wsEmailMeta",
    user.emailVerifiedAt ? t("workspace.emailVerified") : t("workspace.emailUnverified"),
  );
  const emailStatus = $("wsEmailStatus");
  if (emailStatus) {
    emailStatus.textContent = user.emailVerifiedAt ? t("workspace.emailVerified") : t("workspace.emailUnverified");
    emailStatus.classList.toggle("ws-status-ok", Boolean(user.emailVerifiedAt));
  }

  if (keysResult.status === "fulfilled") {
    const keys = keysResult.value || [];
    const active = keys.filter((key) => key.status === "active").length;
    setText("wsKeyCount", String(active));
    setText("wsKeyText", `${active} / ${keys.length}`);
  } else {
    setText("wsKeyCount", "—");
    setText("wsKeyText", "—");
  }

  if (extensionResult.status === "fulfilled") {
    const status = extensionResult.value || {};
    const online = (status.connections || []).filter((connection) => connection.online).length;
    setText("wsExtension", status.connected ? t("workspace.connected") : t("workspace.offline"));
    setText("wsExtensionMeta", status.connected ? `${online} / ${(status.connections || []).length}` : "—");
    setText("wsExtensionText", status.connected ? t("workspace.connected") : t("workspace.offline"));
    $("wsExtensionDot")?.classList.toggle("ws-dot-on", Boolean(status.connected));
  } else {
    setText("wsExtension", "—");
    setText("wsExtensionMeta", "—");
  }

  if (usageResult.status === "fulfilled") {
    const usage = usageResult.value || {};
    const totals = usage.totals || {};
    const quotas = usage.quotas || {};
    setText("wsCalls", formatNumber(totals.toolCalls || 0));
    setText(
      "wsCallsMeta",
      quotas.toolCalls ? `${formatNumber(quotas.toolCalls.used)} / ${formatNumber(quotas.toolCalls.limit)}` : t("workspace.metricCalls"),
    );
    setText("wsQuotaCalls", quotaText(quotas.toolCalls));
    setText("wsQuotaVideo", quotaText(quotas.videoBytes, formatBytes));
    const callsBar = $("wsQuotaCallsBar");
    const videoBar = $("wsQuotaVideoBar");
    if (callsBar) callsBar.style.width = `${quotaPercent(quotas.toolCalls)}%`;
    if (videoBar) videoBar.style.width = `${quotaPercent(quotas.videoBytes)}%`;
  } else {
    setText("wsCalls", "—");
    setText("wsQuotaCalls", "—");
    setText("wsQuotaVideo", "—");
  }
}

window.wsReady?.then((user) => {
  if (!user) return;
  refresh(user).catch(() => toast(t("workspace.offline"), true));
  window.addEventListener("workspace:language", () => {
    refresh(user).catch(() => toast(t("workspace.offline"), true));
  });
});
