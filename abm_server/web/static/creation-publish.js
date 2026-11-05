import { request } from "./api.js";
import { closeModal, confirmAction, escapeHtml, openModal, toast } from "./ui.js";
import { formatDate } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const state = { tasks: [], targets: [], assets: [] };
const ACTIVE = new Set(["queued", "opening", "ready", "needs_attention"]);

function statusLabel(status) {
  const key = `workspace.publishStatus.${status}`;
  const value = t(key);
  return value === key ? status : value;
}

function errorText(task) {
  if (task.errorCode === "ABM_EXTENSION_OFFLINE") return t("workspace.attentionOffline");
  if (task.errorCode === "ABM_CONNECTION_BUSY") return t("workspace.attentionBusy");
  return task.errorMessage || "";
}

function statusClass(status) {
  if (status === "published") return "ok";
  if (["failed", "needs_attention"].includes(status)) return "warn";
  return "";
}

function render() {
  const body = $("publishBody");
  $("publishCount").textContent = t("workspace.totalPublish", { count: state.tasks.length });
  if (!state.tasks.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="ws-empty"><b>${t("workspace.noPublish")}</b><p>${t("workspace.noPublishLead")}</p></div></td></tr>`;
    return;
  }
  body.innerHTML = state.tasks
    .map(
      (task) => `<tr>
        <td><b>${escapeHtml(task.title || "—")}</b><small class="ws-row-sub">${escapeHtml(task.errorMessage || task.publishedUrl || "")}</small></td>
        <td class="ws-hide-sm">${escapeHtml(task.platformLabel)}</td>
        <td><span class="ws-pill ${statusClass(task.status)}">${escapeHtml(statusLabel(task.status))}</span></td>
        <td class="ws-hide-sm">${escapeHtml(formatDate(task.createdAt))}</td>
        <td class="ws-actions-cell">
          ${ACTIVE.has(task.status) ? `<button class="ws-btn ws-btn-small" type="button" data-open="${task.id}">${task.status === "ready" ? t("workspace.focusEditor") : t("workspace.openEditor")}</button>` : ""}
          <button class="ws-btn ws-btn-small" type="button" data-copy="${task.id}">${t("workspace.copyContent")}</button>
          ${task.status === "ready" ? `<button class="ws-btn ws-btn-small" type="button" data-published="${task.id}">${t("workspace.markPublished")}</button>` : ""}
          ${ACTIVE.has(task.status) ? `<button class="ws-btn ws-btn-small" type="button" data-close="${task.id}">${t("workspace.closeTask")}</button>` : ""}
        </td>
      </tr>`,
    )
    .join("");
  body.querySelectorAll("[data-open]").forEach((button) => {
    button.addEventListener("click", () => openTask(button.dataset.open));
  });
  body.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyTask(button.dataset.copy));
  });
  body.querySelectorAll("[data-published]").forEach((button) => {
    button.addEventListener("click", () => markPublished(button.dataset.published));
  });
  body.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => closeTask(button.dataset.close));
  });
}

async function load() {
  try {
    const [tasks, targets, assets] = await Promise.all([
      request("/api/v1/creation/publish/tasks?limit=100"),
      request("/api/v1/creation/publish/targets"),
      request("/api/v1/creation/assets?limit=200"),
    ]);
    state.tasks = tasks.items || [];
    state.targets = targets.items || [];
    state.assets = assets.items || [];
    render();
  } catch (error) {
    $("publishBody").innerHTML = `<tr><td colspan="5"><div class="ws-empty">${t("workspace.loadFailed")}</div></td></tr>`;
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

function openCreate() {
  if (!state.assets.length) return toast(t("workspace.noAssets"), true);
  const platformOptions = state.targets
    .map((target) => `<option value="${target.id}">${escapeHtml(target.label)}</option>`)
    .join("");
  const assetOptions = state.assets
    .map(
      (asset) =>
        `<option value="${asset.id}">${escapeHtml(asset.title)} · ${escapeHtml(asset.masterPlatform)}</option>`,
    )
    .join("");
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${t("workspace.newPublish")}</h2>
      <p>${t("workspace.newPublishLead")}</p>
      <label class="ws-field">${t("workspace.assetTitle")}<select class="ws-select" id="publishAsset">${assetOptions}</select></label>
      <label class="ws-field" style="margin-top:9px">${t("workspace.platformLabel")}<select class="ws-select" id="publishPlatform">${platformOptions}</select></label>
      <div class="ws-actions" style="justify-content:flex-end;margin-top:14px">
        <button class="ws-btn" type="button" data-cancel>${t("workspace.cancel")}</button>
        <button class="ws-btn ws-btn-primary" type="button" id="publishConfirm">${t("workspace.create")}</button>
      </div>
    </div>`,
    t("workspace.newPublish"),
  );
  modal.onclick = (event) => {
    if (event.target.closest("[data-cancel]")) closeModal();
  };
  $("publishConfirm").addEventListener("click", async () => {
    try {
      await request("/api/v1/creation/publish/tasks", {
        method: "POST",
        body: JSON.stringify({
          asset_id: $("publishAsset").value,
          platform: $("publishPlatform").value,
        }),
      });
      closeModal();
      toast(t("workspace.publishCreated"));
      await load();
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
  });
}

async function openTask(taskId) {
  const task = state.tasks.find((item) => item.id === taskId);
  if (task?.status === "ready") {
    toast(t("workspace.editorAlreadyOpen"));
    return;
  }
  try {
    const result = await request(`/api/v1/creation/publish/tasks/${taskId}/open`, {
      method: "POST",
    });
    const updated = result.task;
    if (updated.status === "ready") {
      toast(t("workspace.editorOpened"));
    } else {
      toast(updated.errorMessage || t("workspace.actionFailed"), true);
    }
    await load();
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  }
}

async function copyTask(taskId) {
  try {
    const result = await request(`/api/v1/creation/publish/tasks/${taskId}`);
    const text = `${result.task.title}\n\n${result.task.body}`;
    await navigator.clipboard.writeText(text);
    toast(t("workspace.contentCopied"));
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  }
}

function markPublished(taskId) {
  const url = window.prompt(t("workspace.publishedUrlPrompt"), "");
  if (url === null) return;
  request(`/api/v1/creation/publish/tasks/${taskId}/published`, {
    method: "POST",
    body: JSON.stringify({ url: url.trim() || null }),
  })
    .then(async () => {
      toast(t("workspace.markedPublished"));
      await load();
    })
    .catch((error) => toast(error.message || t("workspace.actionFailed"), true));
}

function closeTask(taskId) {
  confirmAction(t("workspace.closeTask"), t("workspace.closeTaskConfirm"), async () => {
    try {
      await request(`/api/v1/creation/publish/tasks/${taskId}/close`, { method: "POST" });
      toast(t("workspace.taskClosed"));
      await load();
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
  });
}

$("publishCreate").addEventListener("click", openCreate);
window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", render);
});
