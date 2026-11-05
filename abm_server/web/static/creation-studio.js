import { request } from "./api.js";
import { confirmAction, openModal, closeModal, toast } from "./ui.js";
import { formatDate } from "./workspace-admin-common.js";
import { renderMarkdown } from "./markdown.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const assetId = new URLSearchParams(window.location.search).get("asset");
let asset = null;
let latestVersion = null;
let bodyView = "edit";

function renderVersions(items) {
  const list = $("creationVersions");
  if (!items.length) {
    list.innerHTML = `<div class="ws-empty">${t("workspace.noVersions")}</div>`;
    return;
  }
  list.innerHTML = items
    .map(
      (version) => `<div class="ws-list-row">
        <span><b>v${version.versionNo}</b><small>${escapeHtml(formatDate(version.createdAt))}</small></span>
        <span class="right"><span class="ws-pill">${escapeHtml(version.createdBy)}</span></span>
      </div>`,
    )
    .join("");
}
function renderPreview() {
  const preview = $("creationPreview");
  if (!preview) return;
  const source = $("creationBody").value;
  preview.innerHTML = source.trim()
    ? renderMarkdown(source)
    : `<p class="ws-md-empty">${escapeHtml(t("workspace.previewEmpty"))}</p>`;
}

function setBodyView(view) {
  bodyView = view === "preview" ? "preview" : "edit";
  const editing = bodyView === "edit";
  $("creationBody").hidden = !editing;
  $("creationPreview").hidden = editing;
  $("creationBodyEditTab").setAttribute("aria-selected", String(editing));
  $("creationBodyPreviewTab").setAttribute("aria-selected", String(!editing));
  if (editing) {
    $("creationBody").focus();
  } else {
    renderPreview();
  }
}

async function load() {
  if (!assetId) {
    window.location.assign("/creation/assets");
    return;
  }
  try {
    const [detail, versions] = await Promise.all([
      request(`/api/v1/creation/assets/${assetId}`),
      request(`/api/v1/creation/assets/${assetId}/versions`),
    ]);
    asset = detail.asset;
    $("creationAssetTitle").value = asset.title;
    $("creationPlatform").value = asset.masterPlatform;
    $("creationStatus").value = asset.status;
    $("creationBody").value = detail.version?.contentMd || "";
    $("creationStudioTitle").textContent = asset.title;
    $("creationVersionInfo").textContent = t("workspace.versionInfo", {
      count: versions.items?.length || 0,
      updated: formatDate(asset.updatedAt),
    });
    latestVersion = versions.items?.[0] || null;
    renderVersions(versions.items || []);
    renderAiInfo();
    await loadMedia();
    if (bodyView === "preview") renderPreview();
  } catch (error) {
    console.error("[creation-studio] load failed", error);
    toast(t("workspace.loadFailed"), true);
    $("creationVersions").innerHTML = `<div class="ws-empty">${t("workspace.loadFailed")}</div>`;
  }
}

async function save() {
  if (!asset) return;
  const title = $("creationAssetTitle").value.trim();
  if (!title) return toast(t("workspace.assetTitleRequired"), true);
  try {
    await request(`/api/v1/creation/assets/${asset.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title,
        platform: $("creationPlatform").value,
        status: $("creationStatus").value,
      }),
    });
    await request(`/api/v1/creation/assets/${asset.id}/versions`, {
      method: "POST",
      body: JSON.stringify({ content_md: $("creationBody").value }),
    });
    toast(t("workspace.versionSaved"));
    await load();
  } catch {
    toast(t("workspace.saveFailed"), true);
  }
}

function renderAiInfo() {
  const info = $("creationGenerateInfo");
  if (!info) return;
  if (!latestVersion?.model) {
    info.textContent = "";
    return;
  }
  const tokens = (latestVersion.tokensIn || 0) + (latestVersion.tokensOut || 0);
  info.textContent = t("workspace.modelUsed", {
    model: latestVersion.model,
    tokens: tokens.toLocaleString(),
  });
}

async function regenerate() {
  if (!asset) return;
  const sourceIds = latestVersion?.sourceIds || [];
  if (!sourceIds.length) {
    toast(t("workspace.regenerateNoSources"), true);
    return;
  }
  const button = $("creationRegenerate");
  const instruction = $("creationGenerateInstruction").value.trim();
  button.disabled = true;
  button.textContent = t("workspace.generating");
  try {
    await request(`/api/v1/creation/assets/${asset.id}/generate`, {
      method: "POST",
      body: JSON.stringify({
        platform: $("creationPlatform").value,
        source_ids: sourceIds,
        brief: instruction ? { instruction } : {},
      }),
    });
    toast(t("workspace.generateDone"));
    await load();
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  } finally {
    button.disabled = false;
    button.textContent = t("workspace.regenerate");
  }
}

function removeAsset() {
  if (!asset) return;
  confirmAction(t("workspace.moveToTrash"), t("workspace.deleteAssetConfirm", { title: asset.title }), async () => {
    try {
      await request(`/api/v1/creation/assets/${asset.id}`, { method: "DELETE" });
      toast(t("workspace.trashed"));
      window.location.assign("/creation/assets");
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

let mediaItems = [];

const MEDIA_ERROR_KEYS = {
  ABM_CREATION_IMAGE_NOT_CONFIGURED: "workspace.mediaNoModel",
  ABM_CREATION_IMAGE_AUTH: "workspace.mediaNoModel",
  ABM_CREATION_IMAGE_QUOTA: "workspace.mediaQuota",
  ABM_CREATION_STORAGE_FULL: "workspace.mediaStorageFull",
  ABM_CREATION_RENDER_UNAVAILABLE: "workspace.exportRenderUnavailable",
};

function mediaErrorText(error) {
  const key = MEDIA_ERROR_KEYS[error?.code];
  return key ? t(key) : error?.message || t("workspace.mediaGenerateFailed");
}

async function loadMedia() {
  if (!assetId) return;
  try {
    const result = await request(`/api/v1/creation/assets/${assetId}/media`);
    mediaItems = result.items || [];
  } catch (error) {
    console.error("[creation-studio] media load failed", error);
    mediaItems = [];
  }
  renderMedia();
}

function renderMedia() {
  const coverBox = $("creationCoverBox");
  const cover = mediaItems.find((item) => item.role === "cover");
  coverBox.innerHTML = cover
    ? `<img src="${cover.url}" alt="${escapeHtml(cover.prompt || "cover")}" />
       <button class="ws-media-cover-edit" type="button" data-edit="${cover.id}">${escapeHtml(t("workspace.mediaEdit"))}</button>`
    : `<span>${escapeHtml(t("workspace.mediaEmpty"))}</span>`;
  coverBox.querySelectorAll("[data-edit]").forEach((button) => {
    button.addEventListener("click", () => editDialog(button.dataset.edit));
  });

  const grid = $("creationMediaGrid");
  const candidates = mediaItems
    .filter((item) => item.role !== "cover" && item.kind !== "card" && item.status === "ready")
    .slice(0, 8);
  grid.innerHTML = candidates
    .map(
      (item) => `<div class="ws-media-cell">
        <button class="ws-media-thumb" type="button" data-media="${item.id}">
          <img src="${item.url}" alt="${escapeHtml(item.prompt || "")}" />
          <span>${escapeHtml(t("workspace.mediaSetCover"))}</span>
        </button>
        <button class="ws-media-edit" type="button" data-edit="${item.id}">${escapeHtml(t("workspace.mediaEdit"))}</button>
      </div>`,
    )
    .join("");
  grid.querySelectorAll("[data-media]").forEach((button) => {
    button.addEventListener("click", () => setCover(button.dataset.media));
  });
  grid.querySelectorAll("[data-edit]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      editDialog(button.dataset.edit);
    });
  });
}

async function generateMedia() {
  if (!asset) return;
  const prompt = $("creationMediaPrompt").value.trim();
  if (!prompt) {
    toast(t("workspace.mediaNeedPrompt"), true);
    return;
  }
  const button = $("creationMediaGenerate");
  const info = $("creationMediaInfo");
  button.disabled = true;
  button.textContent = t("workspace.mediaGenerating");
  info.textContent = "";
  try {
    const result = await request(`/api/v1/creation/assets/${asset.id}/media/generate`, {
      method: "POST",
      body: JSON.stringify({
        kind: "cover",
        platform: $("creationPlatform").value || "master",
        prompt,
        n: 4,
      }),
    });
    const count = (result.items || []).length;
    toast(t("workspace.mediaGenerated", { count }));
    await loadMedia();
  } catch (error) {
    info.textContent = mediaErrorText(error);
    toast(mediaErrorText(error), true);
  } finally {
    button.disabled = false;
    button.textContent = t("workspace.mediaGenerate");
  }
}

async function setCover(mediaId) {
  try {
    await request(`/api/v1/creation/media/${mediaId}`, {
      method: "PATCH",
      body: JSON.stringify({ role: "cover", kind: "cover" }),
    });
    toast(t("workspace.mediaSetCoverDone"));
    await loadMedia();
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  }
}

function editDialog(mediaId) {
  if (!asset) return;
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.mediaEdit"))}</h2>
      <p>${escapeHtml(t("workspace.mediaEditLead"))}</p>
      <label class="ws-field"><span>${escapeHtml(t("workspace.mediaPrompt"))}</span>
        <textarea class="ws-input" id="mediaEditPrompt" rows="3" placeholder="${escapeHtml(t("workspace.mediaEditPlaceholder"))}"></textarea>
      </label>
      <p class="ws-hint" id="mediaEditError"></p>
      <div class="ws-modal-actions">
        <button class="ws-btn" type="button" data-edit-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" data-edit-action="run">${escapeHtml(t("workspace.mediaEditRun"))}</button>
      </div>
    </div>`,
    t("workspace.mediaEdit"),
  );
  modal.querySelector("#mediaEditPrompt")?.focus();
  modal.onclick = async (event) => {
    const button = event.target.closest("[data-edit-action]");
    if (!button) return;
    if (button.dataset.editAction === "cancel") {
      closeModal();
      return;
    }
    const prompt = modal.querySelector("#mediaEditPrompt").value.trim();
    if (!prompt) {
      toast(t("workspace.mediaNeedPrompt"), true);
      return;
    }
    button.disabled = true;
    button.textContent = t("workspace.mediaGenerating");
    try {
      await request(`/api/v1/creation/assets/${asset.id}/media/generate`, {
        method: "POST",
        body: JSON.stringify({
          kind: "cover",
          platform: $("creationPlatform").value || "master",
          prompt,
          n: 2,
          reference_media_id: mediaId,
        }),
      });
      closeModal();
      toast(t("workspace.mediaGenerated", { count: 2 }));
      await loadMedia();
    } catch (error) {
      modal.querySelector("#mediaEditError").textContent = mediaErrorText(error);
      button.disabled = false;
      button.textContent = t("workspace.mediaEditRun");
    }
  };
}

function exportResultHtml(item) {
  if (item.target === "wechat_html") {
    return `<div class="ws-export-result">
      <p>${escapeHtml(t("workspace.exportDone"))}</p>
      <div class="ws-modal-actions">
        <button class="ws-btn" type="button" data-export-action="copy">${escapeHtml(t("workspace.exportCopy"))}</button>
        <a class="ws-btn" href="${item.downloadUrl}" download>${escapeHtml(t("workspace.exportDownload"))}</a>
        <a class="ws-btn ws-btn-primary" href="${item.downloadUrl}?format=zip" download>${escapeHtml(t("workspace.exportDownloadZip"))}</a>
      </div>
    </div>`;
  }
  const pages = item.files || [];
  return `<div class="ws-export-result">
    <p>${escapeHtml(t("workspace.exportDone"))} · ${escapeHtml(t("workspace.exportPages", { count: pages.length }))}</p>
    <div class="ws-export-grid">
      ${pages
        .map(
          (page) => `<figure class="ws-export-card">
            <img src="${page.url}" alt="page ${page.page}" />
            <figcaption>${escapeHtml(String(page.page))}</figcaption>
          </figure>`,
        )
        .join("")}
    </div>
    <div class="ws-modal-actions">
      <a class="ws-btn ws-btn-primary" href="${item.downloadUrl}" download>${escapeHtml(t("workspace.exportDownloadZip"))}</a>
    </div>
  </div>`;
}

function exportDialog() {
  if (!asset) return;
  let target = "wechat_html";
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.exportTitle"))}</h2>
      <div class="ws-seg ws-export-tabs" role="tablist">
        <button class="ws-seg-btn" type="button" role="tab" data-export-target="wechat_html" aria-selected="true">${escapeHtml(t("workspace.exportWechat"))}</button>
        <button class="ws-seg-btn" type="button" role="tab" data-export-target="xhs_cards" aria-selected="false">${escapeHtml(t("workspace.exportXhs"))}</button>
      </div>
      <div class="ws-export-xhs" hidden>
        <label class="ws-field"><span>${escapeHtml(t("workspace.exportStyle"))}</span>
          <select class="ws-select" id="exportStyle">
            <option value="xhs-paper">Paper</option>
            <option value="xhs-ink">Ink</option>
            <option value="xhs-grid">Grid</option>
          </select>
        </label>
        <label class="ws-check-line"><input type="checkbox" id="exportCover" checked /> ${escapeHtml(t("workspace.exportIncludeCover"))}</label>
        <label class="ws-check-line"><input type="checkbox" id="exportPage" checked /> ${escapeHtml(t("workspace.exportShowPage"))}</label>
      </div>
      <div class="ws-export-output"></div>
      <div class="ws-modal-actions">
        <button class="ws-btn" type="button" data-export-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" data-export-action="run">${escapeHtml(t("workspace.exportRun"))}</button>
      </div>
    </div>`,
    t("workspace.exportTitle"),
  );

  const xhsBox = modal.querySelector(".ws-export-xhs");
  const output = modal.querySelector(".ws-export-output");
  const runButton = modal.querySelector('[data-export-action="run"]');

  modal.querySelectorAll("[data-export-target]").forEach((button) => {
    button.addEventListener("click", () => {
      target = button.dataset.exportTarget;
      modal.querySelectorAll("[data-export-target]").forEach((item) => {
        item.setAttribute("aria-selected", String(item === button));
      });
      xhsBox.hidden = target !== "xhs_cards";
      output.innerHTML = "";
    });
  });

  modal.onclick = async (event) => {
    const button = event.target.closest("[data-export-action]");
    if (!button) return;
    const action = button.dataset.exportAction;
    if (action === "cancel") {
      closeModal();
      return;
    }
    if (action === "copy") {
      const url = output.querySelector("a[download]")?.getAttribute("href") || "";
      try {
        const html = await fetch(url, { credentials: "same-origin" }).then((response) => response.text());
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([html], { type: "text/plain" }),
          }),
        ]);
        toast(t("workspace.exportCopied"));
      } catch {
        toast(t("workspace.exportCopyFailed"), true);
      }
      return;
    }
    if (action === "run") {
      runButton.disabled = true;
      runButton.textContent = t("workspace.exportRunning");
      output.innerHTML = "";
      try {
        const payload = {
          target,
          style_id: target === "xhs_cards" ? modal.querySelector("#exportStyle").value : "default",
          options:
            target === "xhs_cards"
              ? {
                  includeCover: modal.querySelector("#exportCover").checked,
                  showPageNumber: modal.querySelector("#exportPage").checked,
                }
              : {},
        };
        const result = await request(`/api/v1/creation/assets/${asset.id}/exports`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        output.innerHTML = exportResultHtml(result.item);
        toast(t("workspace.exportDone"));
      } catch (error) {
        const key = MEDIA_ERROR_KEYS[error?.code];
        toast(key ? t(key) : error.message || t("workspace.exportFailed"), true);
      } finally {
        runButton.disabled = false;
        runButton.textContent = t("workspace.exportRun");
      }
    }
  };
}

$("creationSaveVersion").addEventListener("click", save);
$("creationDeleteAsset").addEventListener("click", removeAsset);
$("creationRegenerate").addEventListener("click", regenerate);
$("creationBodyEditTab").addEventListener("click", () => setBodyView("edit"));
$("creationBodyPreviewTab").addEventListener("click", () => setBodyView("preview"));
$("creationMediaGenerate").addEventListener("click", generateMedia);
$("creationExportOpen").addEventListener("click", exportDialog);
window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", async () => {
    const title = $("creationAssetTitle")?.value;
    const body = $("creationBody")?.value;
    await load();
    if (title !== undefined) $("creationAssetTitle").value = title;
    if (body !== undefined && $("creationBody")) $("creationBody").value = body;
    if (bodyView === "preview") renderPreview();
  });
});
