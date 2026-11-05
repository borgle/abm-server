import { request } from "./api.js";
import { escapeHtml, openDrawer, closeDrawer, toast, confirmAction } from "./ui.js";
import { formatDate } from "./workspace-admin-common.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const ACTIVE = new Set(["queued", "running", "paused", "needs_attention", "interrupted"]);
const state = { jobs: [], selectedId: null, lastSeq: 0, source: null, poller: null, detail: null };

const statusKey = (status) => `workspace.jobStatus.${status}`;
const statusLabel = (job) => {
  if (job.status === "needs_attention" && job.attention?.reason) {
    const reasonKey = `workspace.jobStatus.reason.${job.attention.reason}`;
    const reasonValue = t(reasonKey);
    if (reasonValue !== reasonKey) return reasonValue;
  }
  const key = statusKey(job.status);
  const value = t(key);
  return value === key ? job.status : value;
};

function engineLabel(id) {
  return { bing: "必应", baidu: "百度", duckduckgo: "DuckDuckGo", google: "Google", xiaohongshu: "小红书" }[id] || id;
}

function renderJobs() {
  const list = $("radarJobs");
  $("radarJobCount").textContent = t("workspace.totalJobs", { count: state.jobs.length });
  if (!state.jobs.length) {
    list.innerHTML = `<div class="ws-empty"><b>${t("workspace.noJobs")}</b><p>${t("workspace.noJobsLead")}</p></div>`;
    return;
  }
  const ordered = [...state.jobs].sort((left, right) => {
    const a = ACTIVE.has(left.status) ? 0 : 1;
    const b = ACTIVE.has(right.status) ? 0 : 1;
    return a - b || (right.createdAt || "").localeCompare(left.createdAt || "");
  });
  list.innerHTML = ordered
    .map(
      (job) => `<button type="button" class="ws-list-row ws-job-row${job.id === state.selectedId ? " on" : ""}" data-job="${job.id}">
        <span><b>${escapeHtml(job.keywords.join(" · "))}</b><small>${escapeHtml(job.engines.map(engineLabel).join(" / "))} · ${escapeHtml(formatDate(job.createdAt))}</small></span>
        <span class="right"><span class="ws-pill ${job.status === "completed" ? "ok" : job.status === "failed" ? "warn" : ""}">${escapeHtml(statusLabel(job))}</span></span>
      </button>`,
    )
    .join("");
  list.querySelectorAll("[data-job]").forEach((button) => {
    button.addEventListener("click", () => selectJob(button.dataset.job));
  });
}

function stopStream() {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  if (state.poller) {
    clearInterval(state.poller);
    state.poller = null;
  }
}

function renderPanel(detail) {
  const job = detail.job;
  state.detail = detail;
  $("radarPanel").hidden = false;
  $("radarJobTitle").textContent = job.keywords.join(" · ");
  $("radarJobMeta").textContent = `${job.engines.map(engineLabel).join(" / ")} · ${t(`workspace.depth.${job.depth}`)} · ${statusLabel(job)}`;
  $("radarCollected").textContent = String(job.pagesCollected);
  $("radarFailed").textContent = String(job.pagesFailed);
  $("radarQueries").textContent = `${job.completedQueries}/${job.totalQueries}`;

  const budget = Number(job.progress?.summary?.pageBudget || 0);
  const ratio = budget ? Math.min(100, Math.round((job.pagesCollected / budget) * 100)) : 0;
  $("radarProgress").querySelector("span").style.width = `${ratio}%`;
  $("radarProgress").setAttribute("aria-valuenow", String(ratio));

  const attention = $("radarAttention");
  if (job.attention) {
    attention.hidden = false;
    attention.textContent = job.attention.message || t("workspace.attentionHint");
    if (job.attention.reason === "extension_offline") {
      attention.textContent = t("workspace.attentionOffline");
    } else if (job.attention.reason === "connection_busy") {
      attention.textContent = t("workspace.attentionBusy");
    } else if (job.attention.reason === "login_required") {
      attention.textContent = t("workspace.attentionLogin");
    } else if (job.attention.reason === "captcha") {
      attention.textContent = t("workspace.attentionCaptcha");
    } else if (job.attention.reason === "blocked") {
      attention.textContent = t("workspace.attentionBlocked");
    }
    if (job.attention.url) {
      attention.textContent += ` · ${job.attention.url}`;
    }
  } else {
    attention.hidden = true;
  }

  const errorBox = $("radarError");
  const lastError = job.progress?.lastError;
  if (job.errorCode || lastError) {
    const code = job.errorCode || lastError?.code || "";
    const message = job.errorMessage || lastError?.message || "";
    errorBox.hidden = false;
    errorBox.innerHTML = `<b>${escapeHtml(code || t("workspace.jobFailed"))}</b> ${escapeHtml(message)}<small>${escapeHtml(t("workspace.errorHint"))}</small>`;
  } else {
    errorBox.hidden = true;
  }

  renderActions(job);
  renderSources(detail.sources || []);
  const log = $("radarLog");
  log.innerHTML = "";
  const history = detail.events || [];
  history.forEach((event) => appendEvent(event));
  if (history.length) state.lastSeq = history[history.length - 1].seq;
  renderEvents(job);
}

function renderActions(job) {
  const actions = $("radarJobActions");
  const buttons = [];
  if (job.status === "running" || job.status === "queued") {
    buttons.push(`<button class="ws-btn" type="button" data-action="pause">${t("workspace.pause")}</button>`);
  }
  if (["paused", "needs_attention", "interrupted"].includes(job.status)) {
    buttons.push(`<button class="ws-btn ws-btn-primary" type="button" data-action="resume">${t("workspace.resume")}</button>`);
  }
  if (ACTIVE.has(job.status)) {
    buttons.push(`<button class="ws-btn" type="button" data-action="cancel">${t("workspace.cancelJob")}</button>`);
  }
  if (!ACTIVE.has(job.status)) {
    buttons.push(`<button class="ws-btn" type="button" data-action="rerun">${t("workspace.rerun")}</button>`);
  }
  if (job.status === "needs_attention" && job.attention?.engine) {
    if (job.attention?.url && job.attention?.phase !== "search") {
      buttons.push(`<button class="ws-btn" type="button" data-action="skip-page">${t("workspace.skipPage")}</button>`);
    }
    buttons.push(`<button class="ws-btn" type="button" data-action="skip">${t("workspace.skipEngine")}</button>`);
  }
  if (state.detail?.sources?.length) {
    buttons.push(`<a class="ws-btn" href="/creation/library?job=${encodeURIComponent(job.id)}">${t("workspace.viewSources")}</a>`);
  }
  actions.innerHTML = buttons.join("");
  actions.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => jobAction(button.dataset.action, job));
  });
}

function renderSources(sources) {
  const body = $("radarSources");
  if (!sources.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="ws-empty">${t("workspace.noSources")}</div></td></tr>`;
    return;
  }
  body.innerHTML = sources
    .map(
      (source) => `<tr data-source="${source.id}">
        <td><b>${escapeHtml(source.title || source.canonicalUrl)}</b></td>
        <td class="ws-hide-sm">${escapeHtml(source.domain)}</td>
        <td><span class="ws-pill">${source.credibility}</span></td>
        <td class="ws-hide-sm">${source.contentLength}</td>
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
}

function renderEvents(job) {
  const log = $("radarLog");
  if (
    (job.status === "paused" || job.status === "needs_attention") &&
    !log.querySelector(".ws-log-line")
  ) {
    log.innerHTML = `<div class="ws-log-line">${escapeHtml(t("workspace.jobWaiting"))}</div>`;
  }
}

function appendEvent(event) {
  const log = $("radarLog");
  if (log.querySelector(".ws-empty")) log.innerHTML = "";
  const line = document.createElement("div");
  line.className = `ws-log-line ${event.level === "warn" ? "warn" : ""}`;
  const time = new Date(event.createdAt);
  line.innerHTML = `<time>${time.toLocaleTimeString()}</time><span>${escapeHtml(event.message)}</span>`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
  while (log.children.length > 200) log.removeChild(log.firstChild);
}

function connectEvents(job) {
  stopStream();
  if (!ACTIVE.has(job.status)) return;
  if (typeof EventSource === "undefined") {
    state.poller = setInterval(() => selectJob(job.id, { keepLog: true }), 2500);
    return;
  }
  const source = new EventSource(
    `/api/v1/creation/research/jobs/${job.id}/events?after=${state.lastSeq}`,
  );
  state.source = source;
  source.addEventListener("job", (message) => {
    const event = JSON.parse(message.data);
    if (event.seq <= state.lastSeq) return;
    state.lastSeq = event.seq;
    appendEvent(event);
  });
  source.addEventListener("done", () => {
    stopStream();
    selectJob(job.id);
    loadJobs();
  });
  source.onerror = () => {
    stopStream();
    if (state.selectedId === job.id) {
      state.poller = setInterval(() => selectJob(job.id, { keepLog: true }), 3000);
    }
  };
}

async function selectJob(jobId, { keepLog = false } = {}) {
  if (state.selectedId !== jobId) {
    state.lastSeq = 0;
    state.selectedId = jobId;
    if (!keepLog) $("radarLog").innerHTML = "";
  }
  try {
    const detail = await request(`/api/v1/creation/research/jobs/${jobId}`);
    renderPanel(detail);
    renderJobs();
    if (!keepLog) connectEvents(detail.job);
  } catch (error) {
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

async function loadJobs(selectId) {
  try {
    const result = await request("/api/v1/creation/research/jobs?limit=20");
    state.jobs = result.items || [];
    renderJobs();
    const target = selectId || state.selectedId || state.jobs[0]?.id;
    if (target) await selectJob(target);
  } catch (error) {
    $("radarJobs").innerHTML = `<div class="ws-empty">${t("workspace.loadFailed")}</div>`;
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

async function jobAction(action, job) {
  if (action === "skip-page") {
    try {
      await request(`/api/v1/creation/research/jobs/${job.id}/resume`, {
        method: "POST",
        body: JSON.stringify({ skip_current: true }),
      });
      toast(t("workspace.jobResumed"));
      state.lastSeq = 0;
      await selectJob(job.id);
      await loadJobs();
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
    return;
  }
  if (action === "skip") {
    try {
      await request(`/api/v1/creation/research/jobs/${job.id}/resume`, {
        method: "POST",
        body: JSON.stringify({ skip_engine: job.attention?.engine }),
      });
      toast(t("workspace.jobResumed"));
      state.lastSeq = 0;
      await selectJob(job.id);
      await loadJobs();
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
    return;
  }
  if (action === "rerun") {
    try {
      const result = await request("/api/v1/creation/research/jobs", {
        method: "POST",
        body: JSON.stringify({
          keywords: job.keywords,
          exclusions: job.exclusions,
          engines: job.engines,
          depth: job.depth,
          language: job.language,
          project_id: job.projectId,
        }),
      });
      toast(t("workspace.jobStarted"));
      state.selectedId = result.job.id;
      state.lastSeq = 0;
      $("radarLog").innerHTML = "";
      await loadJobs(result.job.id);
    } catch (error) {
      toast(error.message || t("workspace.actionFailed"), true);
    }
    return;
  }
  if (action === "cancel") {
    confirmAction(t("workspace.cancelJob"), t("workspace.cancelJobConfirm"), async () => {
      await request(`/api/v1/creation/research/jobs/${job.id}/cancel`, { method: "POST" });
      toast(t("workspace.jobCancelled"));
      await selectJob(job.id);
      await loadJobs();
    });
    return;
  }
  try {
    await request(`/api/v1/creation/research/jobs/${job.id}/${action}`, { method: "POST" });
    toast(action === "pause" ? t("workspace.jobPaused") : t("workspace.jobResumed"));
    state.lastSeq = 0;
    await selectJob(job.id);
    await loadJobs();
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  }
}

async function openSource(sourceId) {
  try {
    const detail = await request(`/api/v1/creation/sources/${sourceId}`);
    const source = detail.source;
    openDrawer({
      title: source.title || source.canonicalUrl,
      sub: `${source.domain} · ${t("workspace.credibility")} ${source.credibility}`,
      body: `<div class="ws-drawer-meta"><span>${escapeHtml(source.author || t("workspace.unknownAuthor"))}</span><span>${escapeHtml(source.fetchedAt ? formatDate(source.fetchedAt) : "")}</span></div>
        <p class="ws-drawer-excerpt">${escapeHtml(source.excerpt || "")}</p>
        <pre class="ws-pre">${escapeHtml(source.contentText || "")}</pre>`,
      footer: `<a class="ws-btn" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${t("workspace.openOriginal")}</a>
        <button class="ws-btn ws-btn-danger" type="button" data-drawer-action="trash">${t("workspace.moveToTrash")}</button>`,
      onAction: async (action) => {
        if (action !== "trash") return;
        await request(`/api/v1/creation/sources/${sourceId}`, { method: "DELETE" });
        closeDrawer();
        toast(t("workspace.trashed"));
        await selectJob(state.selectedId, { keepLog: true });
      },
    });
  } catch (error) {
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

$("radarDiagnostics").addEventListener("click", async () => {
  const box = $("radarDiagResult");
  box.textContent = t("workspace.diagnosing");
  try {
    const result = await request("/api/v1/creation/research/diagnostics", {
      method: "POST",
    });
    if (result.ok) {
      box.textContent = t("workspace.diagnoseOk", {
        title: result.page?.title || "Bing",
      });
    } else {
      box.textContent = `${result.code || t("workspace.jobFailed")}: ${result.message || ""}`;
    }
  } catch (error) {
    box.textContent = error.message || t("workspace.actionFailed");
  }
});

$("radarForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const keywords = $("radarKeywords").value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
  const exclusions = $("radarExclusions").value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
  const engines = [...document.querySelectorAll("#radarEngines input:checked")].map((input) => input.value);
  if (!keywords.length) return toast(t("workspace.keywordsRequired"), true);
  if (!engines.length) return toast(t("workspace.enginesRequired"), true);
  const button = $("radarStart");
  button.disabled = true;
  try {
    const result = await request("/api/v1/creation/research/jobs", {
      method: "POST",
      body: JSON.stringify({
        keywords,
        exclusions,
        engines,
        depth: $("radarDepth").value,
        project_id: window.creationProjectId || null,
      }),
    });
    toast(t("workspace.jobStarted"));
    state.selectedId = result.job.id;
    state.lastSeq = 0;
    $("radarLog").innerHTML = "";
    await loadJobs(result.job.id);
  } catch (error) {
    toast(error.message || t("workspace.actionFailed"), true);
  } finally {
    button.disabled = false;
  }
});

function applyPrefill() {
  const params = new URLSearchParams(window.location.search);
  const keywords = params.get("keywords");
  if (keywords) $("radarKeywords").value = keywords;
  const engines = params.get("engines");
  if (engines) {
    const wanted = new Set(engines.split(","));
    document.querySelectorAll("#radarEngines input").forEach((input) => {
      input.checked = wanted.has(input.value);
    });
  }
  const depth = params.get("depth");
  if (depth) $("radarDepth").value = depth;
}

applyPrefill();
window.wsReady?.then(async (user) => {
  if (!user) return;
  await window.creationProjectsReady;
  await loadJobs();
  window.addEventListener("workspace:language", () => {
    renderJobs();
    if (state.detail) renderPanel(state.detail);
  });
});

window.addEventListener("pagehide", stopStream);
