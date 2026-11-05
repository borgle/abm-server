import { request } from "./api.js";
import { escapeHtml, toast, confirmAction } from "./ui.js";
import { formatDate } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
let items = [];

function typeLabel(type) {
  return type === "source" ? t("workspace.typeSource") : t("workspace.typeAsset");
}

function reasonLabel(reason) {
  if (reason === "expired") return t("workspace.trashExpired");
  if (reason === "manual") return t("workspace.trashManual");
  return reason || "—";
}

function render() {
  const body = $("trashBody");
  $("trashCount").textContent = t("workspace.totalTrash", { count: items.length });
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="ws-empty"><b>${t("workspace.trashEmptyState")}</b><p>${t("workspace.trashEmptyLead")}</p></div></td></tr>`;
    return;
  }
  body.innerHTML = items
    .map(
      (item) => `<tr>
        <td class="ws-hide-sm"><span class="ws-pill">${escapeHtml(typeLabel(item.type))}</span></td>
        <td><b>${escapeHtml(item.title || "—")}</b><small class="ws-row-sub">${escapeHtml(item.subtitle || "")}</small></td>
        <td class="ws-hide-sm">${escapeHtml(reasonLabel(item.reason))}</td>
        <td>${escapeHtml(t("workspace.daysLeft", { count: item.remainingDays }))}</td>
        <td class="ws-actions-cell">
          <button class="ws-btn ws-btn-small" type="button" data-restore="${item.type}:${item.id}">${t("workspace.restore")}</button>
          <button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-purge="${item.type}:${item.id}">${t("workspace.deleteForever")}</button>
        </td>
      </tr>`,
    )
    .join("");
  body.querySelectorAll("[data-restore]").forEach((button) => {
    button.addEventListener("click", () => restore(button.dataset.restore));
  });
  body.querySelectorAll("[data-purge]").forEach((button) => {
    button.addEventListener("click", () => purge(button.dataset.purge));
  });
}

async function load() {
  try {
    const result = await request("/api/v1/creation/trash?limit=200");
    items = result.items || [];
    render();
  } catch (error) {
    $("trashBody").innerHTML = `<tr><td colspan="5"><div class="ws-empty">${t("workspace.loadFailed")}</div></td></tr>`;
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

function splitKey(value) {
  const [type, id] = value.split(":");
  return { type, id };
}

async function restore(value) {
  const { type, id } = splitKey(value);
  const path = type === "source" ? `/api/v1/creation/sources/${id}/restore` : `/api/v1/creation/assets/${id}/restore`;
  try {
    await request(path, { method: "POST" });
    toast(t("workspace.restored"));
    await load();
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  }
}

async function purge(value) {
  const { type, id } = splitKey(value);
  const path = type === "source" ? `/api/v1/creation/sources/${id}/purge` : `/api/v1/creation/assets/${id}/purge`;
  confirmAction(t("workspace.deleteForever"), t("workspace.deleteForeverConfirm"), async () => {
    try {
      await request(path, { method: "DELETE" });
      toast(t("workspace.deletedForever"));
      await load();
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
  });
}

$("trashRefresh").addEventListener("click", load);
$("trashEmpty").addEventListener("click", () => {
  if (!items.length) return toast(t("workspace.trashEmptyState"));
  confirmAction(t("workspace.emptyTrash"), t("workspace.emptyTrashConfirm"), async () => {
    try {
      await request("/api/v1/creation/trash/empty", { method: "POST" });
      toast(t("workspace.trashEmptied"));
      await load();
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
  });
});

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", render);
});
