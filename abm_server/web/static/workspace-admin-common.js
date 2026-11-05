import { request } from "./api.js";
import { currentLanguage, t } from "./workspace-i18n.js";

export const EVENT_LABELS = {
  ABM_ACCOUNT_LOGIN: "workspace.event.login",
  ABM_ACCOUNT_REGISTERED: "workspace.event.registered",
  ABM_ACCOUNT_LOGOUT: "workspace.event.logout",
  ABM_ADMIN_BOOTSTRAPPED: "workspace.event.bootstrapped",
  ABM_ADMIN_USER_UPDATED: "workspace.event.userUpdated",
  ABM_ADMIN_SETTINGS_UPDATED: "workspace.event.settingsUpdated",
  ABM_API_KEY_REVOKED: "workspace.event.keyRevoked",
};

const STATUS_LABELS = {
  pending: "workspace.status.pending",
  active: "workspace.status.active",
  disabled: "workspace.status.disabled",
  rejected: "workspace.status.rejected",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] ? t(STATUS_LABELS[status]) : status;
}

export function statusClass(status) {
  return {
    pending: "ws-status-warn",
    active: "ws-status-ok",
    disabled: "ws-status-bad",
    rejected: "ws-status-bad",
  }[status] || "";
}

export function eventLabel(eventType) {
  return EVENT_LABELS[eventType] ? t(EVENT_LABELS[eventType]) : eventType;
}

export function planLabel(plan) {
  return plan === "pro" ? t("workspace.planPro") : t("workspace.planFree");
}

export function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(currentLanguage() === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function debounce(fn, delay = 280) {
  let timer = null;
  return (...args) => {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

export async function refreshAdminBadge() {
  try {
    const result = await request("/api/v1/admin/users?status=pending&limit=1");
    const count = typeof result.total === "number" ? result.total : (result.items || []).length;
    const badge = document.getElementById("wsApprovalCount");
    if (badge) badge.textContent = String(count);
    return count;
  } catch {
    return null;
  }
}

export function renderPagination(container, page, total, pageSize, onPage) {
  if (!container) return;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  container.replaceChildren();
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = "‹";
  prev.disabled = page <= 1;
  prev.addEventListener("click", () => onPage(page - 1));
  container.appendChild(prev);
  const start = Math.max(1, page - 2);
  const end = Math.min(pages, start + 4);
  for (let index = start; index <= end; index += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = String(index);
    button.className = index === page ? "on" : "";
    button.addEventListener("click", () => onPage(index));
    container.appendChild(button);
  }
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "›";
  next.disabled = page >= pages;
  next.addEventListener("click", () => onPage(page + 1));
  container.appendChild(next);
}
