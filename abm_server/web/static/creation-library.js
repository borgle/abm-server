import { request } from "./api.js";
import { escapeHtml, openDrawer, closeDrawer, openModal, closeModal, toast } from "./ui.js";
import { formatDate, debounce } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const jobFilter = new URLSearchParams(window.location.search).get("job") || "";
const state = { items: [], total: 0, selected: new Set(), generating: false };

const PLATFORMS = [
  ["xiaohongshu", "workspace.platform.xiaohongshu"],
  ["wechat", "workspace.platform.wechat"],
  ["zhihu", "workspace.platform.zhihu"],
  ["shipinhao", "workspace.platform.shipinhao"],
  ["master", "workspace.platform.master"],
];

function selectedIds() {
  return state.items.map((item) => item.id).filter((id) => state.selected.has(id));
}

function syncSelection() {
  $("libraryGenerate").disabled = state.selected.size === 0 || state.generating;
  $("librarySelected").textContent = state.selected.size
    ? t("workspace.selectedSources", { count: state.selected.size })
    : "";
  const all = state.items.length > 0 && state.selected.size === state.items.length;
  $("librarySelectAll").checked = all;
}

function render() {
  const body = $("libraryBody");
  $("libraryCount").textContent = t("workspace.totalSources", { count: state.total });
  if (!state.items.length) {
    body.innerHTML = `<tr><td colspan="7"><div class="ws-empty"><b>${t("workspace.noSources")}</b><p>${t("workspace.noSourcesLead")}</p></div></td></tr>`;
    syncSelection();
    return;
  }
  body.innerHTML = state.items
    .map(
      (source) => `<tr data-source="${source.id}">
        <td class="ws-check"><input type="checkbox" data-select="${source.id}" ${
          state.selected.has(source.id) ? "checked" : ""
        } aria-label="${escapeHtml(t("workspace.selectSource"))}" /></td>
        <td><b>${escapeHtml(source.title || source.canonicalUrl)}</b><small class="ws-row-sub">${escapeHtml(source.excerpt || "")}</small></td>
        <td class="ws-hide-sm">${escapeHtml(source.domain)}</td>
        <td><span class="ws-pill">${source.credibility}</span></td>
        <td class="ws-hide-sm">${source.contentLength}</td>
        <td class="ws-hide-sm">${escapeHtml(formatDate(source.fetchedAt))}</td>
        <td class="ws-actions-cell"><button class="ws-btn ws-btn-small" type="button" data-open="${source.id}">${t("workspace.open")}</button></td>
      </tr>`,
    )
    .join("");
  body.querySelectorAll("[data-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openSource(button.dataset.open);
    });
  });
  body.querySelectorAll("[data-select]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selected.add(input.dataset.select);
      else state.selected.delete(input.dataset.select);
      syncSelection();
    });
  });
  syncSelection();
}

async function load() {
  const query = $("librarySearch").value.trim();
  const kind = $("libraryKind").value;
  const params = new URLSearchParams({ limit: "100" });
  if (query) params.set("q", query);
  if (kind) params.set("kind", kind);
  if (jobFilter) params.set("job_id", jobFilter);
  try {
    const result = await request(`/api/v1/creation/sources?${params.toString()}`);
    state.items = result.items || [];
    state.total = result.total || state.items.length;
    const visible = new Set(state.items.map((item) => item.id));
    state.selected = new Set([...state.selected].filter((id) => visible.has(id)));
    render();
  } catch (error) {
    $("libraryBody").innerHTML = `<tr><td colspan="7"><div class="ws-empty">${t("workspace.loadFailed")}</div></td></tr>`;
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

function selectedDomains(ids) {
  const domains = [];
  for (const item of state.items) {
    if (!ids.includes(item.id)) continue;
    const domain = String(item.domain || "").trim();
    if (domain && !domains.includes(domain)) domains.push(domain);
  }
  return domains;
}

function platformChip(value, key, current) {
  return `<button class="ws-generate-chip" type="button" role="radio" data-platform="${value}" aria-checked="${value === current}">${escapeHtml(t(key))}</button>`;
}

const MAX_GENERATION_SOURCES = 24;

const GENERATE_ERROR_KEYS = {
  ABM_CREATION_MODEL_NOT_CONFIGURED: "workspace.generateNoModel",
  ABM_CREATION_MODEL_AUTH: "workspace.generateModelAuth",
  ABM_CREATION_MODEL_TIMEOUT: "workspace.generateTimeout",
  ABM_CREATION_MODEL_BUSY: "workspace.generateModelBusy",
  ABM_CREATION_MODEL_UNAVAILABLE: "workspace.generateModelBusy",
  ABM_CREATION_GENERATION_LIMIT: "workspace.generateLimit",
  ABM_CREATION_TOKEN_QUOTA: "workspace.generateTokenQuota",
  ABM_CREATION_BAD_DRAFT: "workspace.generateBadDraft",
};

function generateErrorText(error) {
  const key = GENERATE_ERROR_KEYS[error?.code];
  return key ? t(key) : error?.message || t("workspace.actionFailed");
}

function generateDialog() {
  const ids = selectedIds();
  if (!ids.length) {
    toast(t("workspace.generateNeedSources"), true);
    return;
  }
  const used = ids.slice(0, MAX_GENERATION_SOURCES);
  const trimmed = ids.length > used.length;
  const remembered = localStorage.getItem("abm.generate.platform");
  let platform = PLATFORMS.some(([value]) => value === remembered) ? remembered : "xiaohongshu";
  const domains = selectedDomains(used);
  const domainText =
    domains.slice(0, 3).join(" ? ") + (domains.length > 3 ? ` +${domains.length - 3}` : "");
  const optional = `<em>${escapeHtml(t("workspace.optionalMark"))}</em>`;

  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.generateDraft"))}</h2>
      <p class="ws-generate-lead">${escapeHtml(t("workspace.generateDraftLead"))}</p>
      <div class="ws-generate-sources">
        <b>${escapeHtml(t("workspace.generateSelectedSources", { count: used.length }))}</b>
        <small title="${escapeHtml(domains.join(", "))}">${escapeHtml(domainText || t("workspace.noSources"))}</small>
        ${trimmed ? `<small class="ws-generate-limit">${escapeHtml(t("workspace.generateSourceLimit", { count: MAX_GENERATION_SOURCES }))}</small>` : ""}
      </div>
      <span class="ws-generate-label">${escapeHtml(t("workspace.platformLabel"))}</span>
      <div class="ws-generate-platforms" role="radiogroup" aria-label="${escapeHtml(t("workspace.platformLabel"))}">
        ${PLATFORMS.map(([value, key]) => platformChip(value, key, platform)).join("")}
      </div>
      <div class="ws-generate-grid">
        <label class="ws-field"><span>${escapeHtml(t("workspace.assetTitle"))} ${optional}</span><input class="ws-input" id="generateTitle" maxlength="200" placeholder="${escapeHtml(t("workspace.generateTitleHint"))}" /></label>
        <label class="ws-field"><span>${escapeHtml(t("workspace.briefTone"))} ${optional}</span><input class="ws-input" id="generateTone" maxlength="60" placeholder="${escapeHtml(t("workspace.generateToneHint"))}" /></label>
        <label class="ws-field"><span>${escapeHtml(t("workspace.briefGoal"))} ${optional}</span><input class="ws-input" id="generateGoal" maxlength="60" placeholder="${escapeHtml(t("workspace.generateGoalHint"))}" /></label>
        <label class="ws-field"><span>${escapeHtml(t("workspace.briefAudience"))} ${optional}</span><input class="ws-input" id="generateAudience" maxlength="60" placeholder="${escapeHtml(t("workspace.generateAudienceHint"))}" /></label>
        <label class="ws-field ws-generate-wide"><span>${escapeHtml(t("workspace.briefInstruction"))} ${optional}</span><textarea class="ws-input" id="generateInstruction" rows="3" maxlength="300" placeholder="${escapeHtml(t("workspace.generateInstructionHint"))}"></textarea><small class="ws-generate-counter"><span id="generateCount">0</span>/300</small></label>
      </div>
      <p class="ws-generate-hint" id="generateHint">${escapeHtml(t("workspace.generateTimeHint"))}</p>
      <p class="ws-generate-error" id="generateError" hidden></p>
      <div class="ws-modal-actions">
        <button class="ws-btn" type="button" data-modal-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" data-modal-action="generate">${escapeHtml(t("workspace.generate"))}</button>
      </div>
    </div>`,
    t("workspace.generateDraft"),
  );

  const chips = [...modal.querySelectorAll("[data-platform]")];
  const setPlatform = (value) => {
    platform = value;
    chips.forEach((chip) => chip.setAttribute("aria-checked", String(chip.dataset.platform === value)));
  };
  chips.forEach((chip) => chip.addEventListener("click", () => setPlatform(chip.dataset.platform)));

  const instruction = modal.querySelector("#generateInstruction");
  const counter = modal.querySelector("#generateCount");
  const errorBox = modal.querySelector("#generateError");
  const hint = modal.querySelector("#generateHint");
  const generateButton = modal.querySelector('[data-modal-action="generate"]');

  const updateCounter = () => {
    counter.textContent = String(instruction.value.length);
  };
  instruction.addEventListener("input", updateCounter);

  const submit = async () => {
    if (state.generating) return;
    const brief = {};
    for (const [key, id] of [
      ["goal", "#generateGoal"],
      ["audience", "#generateAudience"],
      ["tone", "#generateTone"],
      ["instruction", "#generateInstruction"],
    ]) {
      const value = modal.querySelector(id).value.trim();
      if (value) brief[key] = value;
    }
    const body = { platform, source_ids: used, brief };
    const title = modal.querySelector("#generateTitle").value.trim();
    if (title) body.title = title;

    state.generating = true;
    errorBox.hidden = true;
    modal.setAttribute("aria-busy", "true");
    generateButton.disabled = true;
    generateButton.textContent = t("workspace.generating");
    hint.textContent = t("workspace.generating");
    try {
      const result = await request("/api/v1/creation/generate", {
        method: "POST",
        body: JSON.stringify(body),
      });
      localStorage.setItem("abm.generate.platform", platform);
      if (!errorBox.isConnected) {
        toast(t("workspace.generateDoneLibrary"));
        return;
      }
      closeModal();
      toast(t("workspace.generateDone"));
      window.location.assign(`/creation/studio?asset=${encodeURIComponent(result.asset.id)}`);
    } catch (error) {
      if (errorBox.isConnected) {
        errorBox.textContent = generateErrorText(error);
        errorBox.hidden = false;
        modal.removeAttribute("aria-busy");
        hint.textContent = t("workspace.generateTimeHint");
        generateButton.disabled = false;
        generateButton.textContent = t("workspace.generate");
      } else {
        toast(error.message || t("workspace.actionFailed"), true);
      }
    } finally {
      state.generating = false;
    }
  };

  modal.onclick = (event) => {
    const button = event.target.closest("[data-modal-action]");
    if (!button) return;
    if (button.dataset.modalAction === "cancel") {
      closeModal();
      return;
    }
    submit();
  };
  modal.querySelectorAll("input, textarea").forEach((field) => {
    field.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    });
  });

  setPlatform(platform);
  updateCounter();
  modal.querySelector("#generateTitle")?.focus();
}

async function openSource(sourceId) {
  try {
    const detail = await request(`/api/v1/creation/sources/${sourceId}`);
    const source = detail.source;
    openDrawer({
      title: source.title || source.canonicalUrl,
      sub: `${source.domain} · ${t("workspace.credibility")} ${source.credibility} · ${source.contentLength} ${t("workspace.wordsUnit")}`,
      body: `<div class="ws-drawer-meta"><span>${escapeHtml(source.author || t("workspace.unknownAuthor"))}</span><span>${escapeHtml(formatDate(source.fetchedAt))}</span><span>${escapeHtml(source.engine)}</span></div>
        <p class="ws-drawer-excerpt">${escapeHtml(source.excerpt || "")}</p>
        <pre class="ws-pre">${escapeHtml(source.contentText || "")}</pre>`,
      footer: `<a class="ws-btn" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${t("workspace.openOriginal")}</a>
        <button class="ws-btn ws-btn-danger" type="button" data-drawer-action="trash">${t("workspace.moveToTrash")}</button>`,
      onAction: async (action) => {
        if (action !== "trash") return;
        await request(`/api/v1/creation/sources/${sourceId}`, { method: "DELETE" });
        closeDrawer();
        toast(t("workspace.trashed"));
        await load();
      },
    });
  } catch (error) {
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

$("librarySearch").addEventListener("input", debounce(load, 280));
$("libraryKind").addEventListener("change", load);
$("libraryRefresh").addEventListener("click", load);
$("libraryGenerate").addEventListener("click", generateDialog);
$("librarySelectAll").addEventListener("change", (event) => {
  state.selected = event.target.checked
    ? new Set(state.items.map((item) => item.id))
    : new Set();
  render();
});

function renderJobFilter() {
  if (!jobFilter) return;
  $("libraryJobFilter").innerHTML = `${escapeHtml(t("workspace.filteredByJob"))} <a href="/creation/library">${escapeHtml(t("workspace.clearFilter"))}</a>`;
}

renderJobFilter();
window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", render);
});
