import { request } from "./api.js";
import { confirmAction, toast } from "./ui.js";
import { openCreateAsset } from "./creation-common.js";
import { formatDate } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
let assets = [];

function statusLabel(status) {
  return t("workspace.status." + status);
}

function render() {
  const query = $("creationAssetSearch").value.trim().toLowerCase();
  const status = $("creationAssetStatus").value;
  const list = assets.filter(
    (asset) =>
      (!query || asset.title.toLowerCase().includes(query)) &&
      (!status || asset.status === status),
  );
  $("creationAssetCount").textContent = t("workspace.totalAssets", { count: list.length });
  const body = $("creationAssetsBody");
  if (!list.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="ws-empty"><b>${t("workspace.noAssets")}</b><p>${t("workspace.noAssetsLead")}</p></div></td></tr>`;
    return;
  }
  body.innerHTML = list
    .map(
      (asset) => `<tr>
        <td><div class="ws-asset-cell">${
          asset.coverUrl
            ? `<img class="ws-asset-thumb" src="${asset.coverUrl}" alt="" loading="lazy" />`
            : `<span class="ws-asset-thumb ws-asset-thumb-empty" aria-hidden="true"></span>`
        }<b>${escapeHtml(asset.title)}</b></div></td>
        <td class="ws-hide-sm">${escapeHtml(asset.masterPlatform)}</td>
        <td><span class="ws-pill">${escapeHtml(statusLabel(asset.status))}</span></td>
        <td class="ws-hide-sm">${escapeHtml(formatDate(asset.updatedAt))}</td>
        <td class="ws-actions-cell"><a class="ws-btn ws-btn-small" href="/creation/studio?asset=${asset.id}">${t("workspace.open")}</a>
          <button class="ws-icon-btn ws-icon-btn-sm ws-icon-btn-danger" type="button" data-delete="${asset.id}" data-title="${escapeHtml(asset.title)}" aria-label="${t("workspace.moveToTrash")}" title="${t("workspace.moveToTrash")}"><svg class="ws-ico ws-ico-sm" aria-hidden="true"><use href="#i-trash" /></svg></button></td>
      </tr>`,
    )
    .join("");
  body.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteAsset(button.dataset.delete, button.dataset.title));
  });
}

async function deleteAsset(assetId, title) {
  confirmAction(
    t("workspace.moveToTrash"),
    t("workspace.deleteAssetConfirm", { title }),
    async () => {
      try {
        await request(`/api/v1/creation/assets/${assetId}`, { method: "DELETE" });
        toast(t("workspace.trashed"));
        await load();
      } catch (error) {
        toast(error.message || t("workspace.actionFailed"), true);
      }
    },
  );
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function load() {
  try {
    await window.creationProjectsReady;
    const query = window.creationProjectId ? `?project_id=${encodeURIComponent(window.creationProjectId)}&limit=200` : "?limit=200";
    const result = await request(`/api/v1/creation/assets${query}`);
    assets = result.items || [];
    render();
  } catch {
    $("creationAssetsBody").innerHTML = `<tr><td colspan="5"><div class="ws-empty">${t("workspace.loadFailed")}</div></td></tr>`;
  }
}

$("creationNewAsset").addEventListener("click", openCreateAsset);
$("creationAssetSearch").addEventListener("input", render);
$("creationAssetStatus").addEventListener("change", render);
window.addEventListener("creation:project", load);

async function applyTemplatePrefill() {
  const templateId = new URLSearchParams(window.location.search).get("template");
  if (!templateId) return;
  try {
    const result = await request("/api/v1/creation/templates");
    const template = (result.items || []).find((item) => item.id === templateId);
    if (!template || template.action?.kind !== "asset") return;
    openCreateAsset({
      title: template.action.title || template.name,
      platform: template.action.platform || "master",
    });
  } catch {
    /* template prefill is best effort */
  }
}

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  applyTemplatePrefill();
  window.addEventListener("workspace:language", () => {
    render();
    load();
  });
});
