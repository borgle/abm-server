import { request } from "./api.js";
import { confirmAction, escapeHtml, toast } from "./ui.js";
import { formatDate, refreshAdminBadge } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
let pending = [];

function card(user) {
  return `
    <article class="ws-card ws-approval-card" data-user-id="${user.id}">
      <div class="ws-card-head" style="margin-bottom: 0">
        <div><h2>${escapeHtml(user.displayName)}</h2><p>${escapeHtml(user.email)}</p></div>
        <span class="ws-status ws-status-warn">${escapeHtml(t("workspace.status.pending"))}</span>
      </div>
      <p>${escapeHtml(user.applicationNote || t("workspace.noApplicationNote"))}</p>
      <div class="ws-approval-meta"><span>${escapeHtml(formatDate(user.createdAt))}</span><span>${escapeHtml(user.planCode === "pro" ? "Pro" : "Free")}</span></div>
      <div class="ws-approval-actions">
        <button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-approve-action="reject" data-id="${user.id}">${escapeHtml(t("workspace.reject"))}</button>
        <button class="ws-btn ws-btn-small ws-btn-primary" type="button" data-approve-action="approve" data-id="${user.id}">${escapeHtml(t("workspace.approve"))}</button>
      </div>
    </article>`;
}

function render() {
  const grid = $("wsApprovalsGrid");
  $("wsPendingBadge").textContent = String(pending.length);
  if (!pending.length) {
    grid.innerHTML = `<div class="ws-empty" style="grid-column: 1 / -1"><b>${escapeHtml(t("workspace.noApprovals"))}</b><p>${escapeHtml(t("workspace.noApprovalsLead"))}</p></div>`;
    return;
  }
  grid.innerHTML = pending.map(card).join("");
  grid.querySelectorAll("[data-approve-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const user = pending.find((item) => item.id === button.dataset.id);
      if (!user) return;
      if (button.dataset.approveAction === "approve") {
        patch(user, "active");
      } else {
        confirmAction(
          t("workspace.rejectTitle"),
          t("workspace.rejectBody", { name: user.displayName }),
          () => patch(user, "rejected"),
        );
      }
    });
  });
}

async function load() {
  $("wsApprovalsGrid").innerHTML = `<div class="ws-empty" style="grid-column: 1 / -1">${escapeHtml(t("workspace.loading"))}</div>`;
  try {
    const result = await request("/api/v1/admin/users?status=pending&limit=100&offset=0");
    pending = result.items || [];
    render();
    refreshAdminBadge();
  } catch {
    $("wsApprovalsGrid").innerHTML = `<div class="ws-empty" style="grid-column: 1 / -1">${escapeHtml(t("workspace.loadFailed"))}</div>`;
    toast(t("workspace.loadFailed"), true);
  }
}

async function patch(user, status) {
  try {
    await request(`/api/v1/admin/users/${user.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    toast(t(status === "active" ? "workspace.approved" : "workspace.rejected", { name: user.displayName }));
    await load();
    refreshAdminBadge();
  } catch {
    toast(t("workspace.updateFailed"), true);
  }
}

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", () => load());
});
