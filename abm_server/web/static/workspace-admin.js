import { formatTime, request } from "./api.js";
import { toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);

const EVENT_LABELS = {
  ABM_ACCOUNT_LOGIN: "workspace.event.login",
  ABM_ACCOUNT_REGISTERED: "workspace.event.registered",
  ABM_ACCOUNT_LOGOUT: "workspace.event.logout",
  ABM_ADMIN_BOOTSTRAPPED: "workspace.event.bootstrapped",
  ABM_ADMIN_USER_UPDATED: "workspace.event.userUpdated",
  ABM_ADMIN_SETTINGS_UPDATED: "workspace.event.settingsUpdated",
  ABM_API_KEY_REVOKED: "workspace.event.keyRevoked",
};

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function renderAudit(items) {
  const list = $("wsAdminAudit");
  if (!list) return;
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "ws-empty";
    empty.textContent = t("workspace.noAudit");
    list.appendChild(empty);
    return;
  }
  for (const event of items) {
    const row = document.createElement("div");
    row.className = "ws-list-row";
    const info = document.createElement("span");
    const title = document.createElement("b");
    title.textContent = EVENT_LABELS[event.eventType]
      ? t(EVENT_LABELS[event.eventType])
      : event.eventType || "—";
    const meta = document.createElement("small");
    meta.textContent = `${formatTime(event.createdAt)} · ${event.subjectName || event.subjectUserId || "-"}`;
    info.append(title, meta);
    row.appendChild(info);
    list.appendChild(row);
  }
}

async function refresh() {
  const [usersResult, settingsResult, auditResult] = await Promise.allSettled([
    request("/api/v1/admin/users?limit=100"),
    request("/api/v1/admin/settings"),
    request("/api/v1/admin/audit?limit=5"),
  ]);

  if (usersResult.status === "fulfilled") {
    const items = usersResult.value.items || [];
    const pending = items.filter((user) => user.status === "pending").length;
    const active = items.filter((user) => user.status === "active").length;
    setText("wsPending", String(pending));
    setText("wsActive", String(active));
    setText("wsTotalMeta", `${active} / ${items.length}`);
    const navCount = $("wsApprovalCount");
    if (navCount) navCount.textContent = String(pending);
  } else {
    setText("wsPending", "—");
    setText("wsActive", "—");
  }

  if (settingsResult.status === "fulfilled") {
    setText(
      "wsApprovalMode",
      settingsResult.value.registrationRequireApproval ? t("workspace.approvalOn") : t("workspace.approvalOff"),
    );
  } else {
    setText("wsApprovalMode", "—");
  }

  if (auditResult.status === "fulfilled") {
    const items = auditResult.value.items || [];
    setText("wsAuditCount", String(items.length));
    renderAudit(items);
  } else {
    setText("wsAuditCount", "—");
  }
}

function schedule() {
  let timer = null;
  const tick = () => {
    if (document.hidden || document.body.dataset.section !== "overview") return;
    refresh().catch(() => toast(t("workspace.offline"), true));
  };
  const start = () => {
    stop();
    timer = window.setInterval(tick, 30_000);
  };
  const stop = () => {
    if (timer) window.clearInterval(timer);
    timer = null;
  };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stop();
    } else {
      tick();
      start();
    }
  });
  start();
}

window.wsReady?.then((user) => {
  if (!user) return;
  refresh().catch(() => toast(t("workspace.offline"), true));
  schedule();
  window.addEventListener("workspace:language", () => {
    refresh().catch(() => toast(t("workspace.offline"), true));
  });
});
