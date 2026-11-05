import { accountError, initAccountPage, t } from "./account-i18n.js";
import {
  formatTime,
  logout,
  request,
  requireUser,
  showNotice,
} from "./api.js";

const userList = document.getElementById("user-list");
const auditList = document.getElementById("audit-list");
const statusFilter = document.getElementById("status-filter");
const approvalSetting = document.getElementById("approval-setting");

let currentUsers = [];

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function auditLabel(eventType) {
  const key = `admin.event.${eventType}`;
  const label = t(key);
  return label === key ? eventType : label;
}
let currentAudit = [];
let usersLoaded = false;
let auditLoaded = false;

initAccountPage({
  titleKey: "admin.pageTitle",
  onChange() {
    if (usersLoaded) {
      renderUsers();
    }
    if (auditLoaded) {
      renderAudit();
    }
  },
});

function statusLabel(status) {
  const key = `admin.status.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

async function updateUser(user, patch) {
  try {
    await request(`/api/v1/admin/users/${user.id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    showNotice(t("admin.userUpdated"));
    await refreshUsers();
    await refreshAudit();
  } catch (error) {
    showNotice(accountError(error), true);
  }
}

function renderUser(user) {
  const row = document.createElement("div");
  row.className = "list-row";

  const info = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = user.displayName;
  const badge = document.createElement("span");
  badge.className = `status ${user.status}`;
  badge.textContent = statusLabel(user.status);
  title.append(" ", badge);
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = t("admin.requestedAt", {
    email: user.email,
    plan: user.planCode.toUpperCase(),
    time: formatTime(user.createdAt),
  });
  info.append(title, meta);
  if (user.usage) {
    const usage = document.createElement("div");
    usage.className = "meta";
    usage.textContent = t("admin.usageMeta", {
      calls: user.usage.toolCalls,
      jobs: user.usage.videoJobs,
      bytes: formatBytes(user.usage.videoBytes),
    });
    info.appendChild(usage);
  }
  if (user.applicationNote) {
    const note = document.createElement("div");
    note.className = "meta";
    note.textContent = t("admin.applicationNote", { note: user.applicationNote });
    info.appendChild(note);
  }

  const actions = document.createElement("div");
  actions.className = "admin-controls";
  if (user.status === "pending") {
    const approve = document.createElement("button");
    approve.className = "button small primary";
    approve.textContent = t("admin.approve");
    approve.addEventListener("click", () => updateUser(user, { status: "active" }));
    const reject = document.createElement("button");
    reject.className = "button small danger";
    reject.textContent = t("admin.reject");
    reject.addEventListener("click", () => updateUser(user, { status: "rejected" }));
    actions.append(approve, reject);
  }
  if (user.status === "active") {
    const disable = document.createElement("button");
    disable.className = "button small danger";
    disable.textContent = t("admin.disable");
    disable.addEventListener("click", () => updateUser(user, { status: "disabled" }));
    actions.appendChild(disable);
  }
  if (user.status === "rejected" || user.status === "disabled") {
    const enable = document.createElement("button");
    enable.className = "button small";
    enable.textContent = t("admin.enable");
    enable.addEventListener("click", () => updateUser(user, { status: "active" }));
    actions.appendChild(enable);
  }

  const plan = document.createElement("select");
  plan.innerHTML = '<option value="free">Free</option><option value="pro">Pro</option>';
  plan.value = user.planCode;
  const expiry = document.createElement("input");
  expiry.type = "datetime-local";
  expiry.value = user.planExpiresAt ? user.planExpiresAt.slice(0, 16) : "";
  const savePlan = document.createElement("button");
  savePlan.className = "button small";
  savePlan.textContent = t("admin.savePlan");
  savePlan.addEventListener("click", () =>
    updateUser(user, {
      plan_code: plan.value,
      plan_expires_at: expiry.value ? new Date(expiry.value).toISOString() : null,
    }),
  );
  actions.append(plan, expiry, savePlan);

  row.append(info, actions);
  return row;
}

function renderUsers() {
  userList.replaceChildren();
  if (currentUsers.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("admin.noUsers");
    userList.appendChild(empty);
    return;
  }
  currentUsers.forEach((user) => userList.appendChild(renderUser(user)));
}

function renderAudit() {
  auditList.replaceChildren();
  if (currentAudit.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("admin.noAudit");
    auditList.appendChild(empty);
    return;
  }
  for (const event of currentAudit) {
    const row = document.createElement("div");
    row.className = "list-row";
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = auditLabel(event.eventType);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${formatTime(event.createdAt)} · ${event.subjectUserId || "-"}`;
    info.append(title, meta);
    row.appendChild(info);
    auditList.appendChild(row);
  }
}

async function refreshUsers() {
  const status = statusFilter.value;
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const result = await request(`/api/v1/admin/users${query}`);
  currentUsers = result.items;
  usersLoaded = true;
  renderUsers();
}

async function refreshSettings() {
  const settings = await request("/api/v1/admin/settings");
  approvalSetting.checked = settings.registrationRequireApproval;
}

async function refreshAudit() {
  const result = await request("/api/v1/admin/audit?limit=50");
  currentAudit = result.items;
  auditLoaded = true;
  renderAudit();
}

statusFilter.addEventListener("change", () => {
  refreshUsers().catch((error) => showNotice(accountError(error), true));
});
document.getElementById("refresh-audit").addEventListener("click", () => {
  refreshAudit().catch((error) => showNotice(accountError(error), true));
});
approvalSetting.addEventListener("change", async () => {
  approvalSetting.disabled = true;
  try {
    await request("/api/v1/admin/settings", {
      method: "PATCH",
      body: JSON.stringify({
        registration_require_approval: approvalSetting.checked,
      }),
    });
    showNotice(t("admin.approvalUpdated"));
    await refreshAudit();
  } catch (error) {
    approvalSetting.checked = !approvalSetting.checked;
    showNotice(accountError(error), true);
  } finally {
    approvalSetting.disabled = false;
  }
});
document.getElementById("logout-button").addEventListener("click", logout);

async function init() {
  const user = await requireUser();
  if (!user) return;
  if (user.role !== "admin") {
    window.location.assign("/console");
    return;
  }
  await Promise.all([refreshUsers(), refreshSettings(), refreshAudit()]);
}

init().catch((error) => showNotice(accountError(error), true));
