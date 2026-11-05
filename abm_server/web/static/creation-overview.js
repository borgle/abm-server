import { request } from "./api.js";
import { openCreateAsset } from "./creation-common.js";
import { formatDate } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);

function render(projects, assets) {
  $("creationProjectCount").textContent = String(projects.length);
  $("creationAssetCount").textContent = String(assets.length);
  $("creationVersionCount").textContent = String(assets.filter((asset) => asset.status === "draft").length);
  $("creationWordCount").textContent = String(assets.filter((asset) => asset.status === "published").length);
  const flowResearch = $("creationFlowResearch");
  if (flowResearch) {
    flowResearch.textContent = t("workspace.flowProjects", { count: projects.length });
    $("creationFlowDraft").textContent = t("workspace.flowAssets", {
      count: assets.filter((asset) => asset.status === "draft").length,
    });
    $("creationFlowReview").textContent = t("workspace.flowAssets", {
      count: assets.filter((asset) => asset.status === "review").length,
    });
    $("creationFlowPublished").textContent = t("workspace.flowAssets", {
      count: assets.filter((asset) => asset.status === "published").length,
    });
  }
  const list = $("creationRecentAssets");
  if (!assets.length) {
    list.innerHTML = `<div class="ws-empty"><b>${t("workspace.noAssets")}</b><p>${t("workspace.noAssetsLead")}</p></div>`;
    return;
  }
  list.innerHTML = assets
    .slice(0, 5)
    .map(
      (asset) => `<div class="ws-list-row">
        <span><b>${escapeHtml(asset.title)}</b><small>${escapeHtml(asset.masterPlatform)} · ${escapeHtml(t("workspace.status." + asset.status))}</small></span>
        <span class="right"><span class="ws-date">${escapeHtml(formatDate(asset.updatedAt))}</span><a class="ws-btn ws-btn-small" href="/creation/studio?asset=${asset.id}">${t("workspace.open")}</a></span>
      </div>`,
    )
    .join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function load() {
  try {
    const query = window.creationProjectId
      ? `?project_id=${encodeURIComponent(window.creationProjectId)}&limit=100`
      : "?limit=100";
    const [projects, assets] = await Promise.all([
      window.creationProjectsReady,
      request(`/api/v1/creation/assets${query}`),
    ]);
    render(projects || [], assets.items || []);
  } catch {
    $("creationRecentAssets").innerHTML = `<div class="ws-empty">${t("workspace.loadFailed")}</div>`;
  }
}

$("creationNewAsset").addEventListener("click", openCreateAsset);
window.addEventListener("creation:project", load);
window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", load);
});
