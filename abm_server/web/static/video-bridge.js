import { showNotice } from "./api.js";
import { accountError, initAccountPage, t } from "./account-i18n.js";

const form = document.getElementById("bridge-form");
const keyInput = document.getElementById("bridge-key");
const extensionInput = document.getElementById("bridge-extension");
const autoInput = document.getElementById("bridge-auto");
const stateElement = document.getElementById("bridge-state");
const logElement = document.getElementById("bridge-log");
const metaElement = document.getElementById("bridge-meta");

const inFlight = new Set();
const knownJobs = new Map();
let timer = null;
let bridgeToken = "";
let ownsBridgeLock = false;
let stateKey = "bridge.state.idle";
let metaKey = "bridge.autoMeta";
let metaValues = {};
let metaRaw = "";
let logHasContent = false;

// 从扩展 popup 打开时带 lang 参数，让桥页面沿用 popup 的语言。
const requestedLanguage = new URLSearchParams(window.location.search).get("lang");
if (requestedLanguage === "en" || requestedLanguage === "zh") {
  try {
    localStorage.setItem("abm.lang", requestedLanguage);
  } catch {
    // Local storage can be unavailable; the page still uses the query language.
  }
}

function renderState() {
  stateElement.textContent = t(stateKey);
}

function renderMeta() {
  metaElement.textContent = metaKey ? t(metaKey, metaValues) : metaRaw;
}

function setState(key) {
  stateKey = key;
  renderState();
}

function setMeta(key, values = {}) {
  metaKey = key;
  metaValues = values;
  metaRaw = "";
  renderMeta();
}

function setMetaRaw(message) {
  metaKey = "";
  metaRaw = message;
  renderMeta();
}

initAccountPage({
  titleKey: "bridge.pageTitle",
  onChange() {
    renderState();
    renderMeta();
    if (!logHasContent) {
      logElement.textContent = t("bridge.logIdle");
    }
  },
});

function errorText(error) {
  if (error?.code) return accountError(error);
  return error?.message || t("error.generic");
}

async function acquireBridgeLock() {
  if (!navigator.locks) {
    ownsBridgeLock = true;
    return true;
  }
  return new Promise((resolve) => {
    void navigator.locks.request(
      "abm-video-bridge-owner",
      { ifAvailable: true },
      async (lock) => {
        if (!lock) {
          resolve(false);
          return;
        }
        ownsBridgeLock = true;
        resolve(true);
        await new Promise((release) => {
          window.addEventListener("pagehide", release, { once: true });
        });
        ownsBridgeLock = false;
      },
    );
  });
}

function log(message) {
  logHasContent = true;
  const locale = document.documentElement.lang.startsWith("en") ? "en-US" : "zh-CN";
  const time = new Date().toLocaleTimeString(locale);
  logElement.textContent += `\n[${time}] ${message}`;
}

function apiHeaders() {
  return { Authorization: `Bearer ${bridgeToken}` };
}

async function exchangeBridgeToken(apiKey) {
  const response = await fetch("/api/v1/video/bridge-token", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body?.error?.message || `HTTP ${response.status}`);
    error.code = body?.error?.code;
    error.status = response.status;
    throw error;
  }
  if (!body?.token) {
    throw new Error(t("bridge.error.token"));
  }
  bridgeToken = body.token;
  return body;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...apiHeaders(),
      ...(options.headers || {}),
    },
  });
  const body = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body?.error?.message || `HTTP ${response.status}`);
    error.code = body?.error?.code;
    error.status = response.status;
    throw error;
  }
  return body;
}

async function sendExtension(type, payload) {
  const extensionId = extensionInput.value.trim();
  const result = await chrome.runtime.sendMessage(extensionId, { type, payload });
  if (result && result.ok === false) {
    throw new Error(
      t("bridge.error.rejected", {
        type,
        error: result.error || t("error.generic"),
      }),
    );
  }
  return result;
}

async function postStep(jobId, step, success, error = null) {
  await api(`/api/v1/video/jobs/${encodeURIComponent(jobId)}/result`, {
    method: "POST",
    body: JSON.stringify({ step, success, error }),
  });
}

async function processJob(job) {
  inFlight.add(job.sessionId);
  log(t("bridge.log.start", { file: job.fileName, chunks: job.totalChunks }));
  try {
    await sendExtension("abm.video.begin", {
      sessionId: job.sessionId,
      fileName: job.fileName,
      fileType: job.fileType,
      fileSize: job.fileSize,
      totalChunks: job.totalChunks,
    });
    await postStep(job.sessionId, "start", true);
    for (let index = 0; index < job.totalChunks; index += 1) {
      const chunk = await api(
        `/api/v1/video/jobs/${encodeURIComponent(job.sessionId)}/chunks/${index}`,
      );
      await sendExtension("abm.video.chunk", {
        sessionId: job.sessionId,
        index,
        totalChunks: job.totalChunks,
        base64: chunk.base64,
      });
      await postStep(job.sessionId, "chunk", true);
      log(
        t("bridge.log.chunk", {
          file: job.fileName,
          current: index + 1,
          total: job.totalChunks,
        }),
      );
    }
    await sendExtension("abm.video.finish", { sessionId: job.sessionId });
    await postStep(job.sessionId, "complete", true);
    log(t("bridge.log.done", { file: job.fileName }));
  } catch (error) {
    const message = errorText(error);
    log(t("bridge.log.failed", { error: message }));
    await postStep(job.sessionId, "start", false, message).catch(() => {});
  } finally {
    inFlight.delete(job.sessionId);
  }
}

async function poll() {
  if (!bridgeToken || !autoInput.checked || !ownsBridgeLock) return;
  try {
    const result = await api("/api/v1/video/jobs");
    setState("bridge.state.running");
    const jobs = result.jobs || [];
    const bridgeJobs = jobs.filter(
      (job) =>
        ["pending", "delivering"].includes(job.status) && job.delivery === "bridge",
    );
    setMeta("bridge.meta.jobs", {
      id: extensionInput.value.trim(),
      jobs: jobs.length,
      pending: bridgeJobs.length,
    });
    for (const job of jobs) {
      const previous = knownJobs.get(job.sessionId);
      if (previous !== job.status) {
        log(`${job.fileName} · ${job.delivery} · ${job.status}`);
        knownJobs.set(job.sessionId, job.status);
      }
    }
    for (const job of bridgeJobs) {
      if (!inFlight.has(job.sessionId)) {
        void processJob(job);
      }
    }
  } catch (error) {
    setState("bridge.state.error");
    log(t("bridge.log.pollFailed", { error: errorText(error) }));
  }
}

async function configure() {
  if (!bridgeToken) {
    const apiKey = keyInput.value.trim();
    if (!apiKey) throw new Error(t("bridge.error.apiKey"));
    await exchangeBridgeToken(apiKey);
    keyInput.value = "";
  }
  if (!extensionInput.value.trim()) throw new Error(t("bridge.error.extensionId"));
  if (!(await acquireBridgeLock())) {
    throw new Error(t("bridge.error.lock"));
  }
  const config = await api("/api/v1/video/config");
  if (!extensionInput.value.trim() && config.extensionId) {
    extensionInput.value = config.extensionId;
  }
  localStorage.setItem("abm_bridge_extension", extensionInput.value.trim());
  await sendExtension("abm.bridge.check", {});
  setState("bridge.state.ready");
  setMeta("bridge.meta.default", {
    id: extensionInput.value.trim(),
    delivery: config.delivery,
  });
  log(
    t("bridge.log.connected", {
      id: extensionInput.value.trim(),
      delivery: config.delivery,
    }),
  );
  clearInterval(timer);
  timer = setInterval(() => void poll(), 2000);
  await poll();
}

async function autoConfigure() {
  setState("bridge.state.configuring");
  let extensionId =
    new URLSearchParams(window.location.search).get("extensionId") ||
    extensionInput.value.trim();
  if (!extensionId) {
    const response = await fetch("/api/v1/video/extension", { cache: "no-store" });
    if (response.ok) extensionId = (await response.json()).extensionId || "";
  }
  if (!extensionId) {
    throw new Error(t("bridge.error.noExtension"));
  }
  extensionInput.value = extensionId;
  const config = await sendExtension("abm.bridge.config", {});
  if (config?.bridgeToken) {
    bridgeToken = config.bridgeToken;
  } else if (config?.apiKey) {
    // Older extension: exchange once and immediately discard the key.
    await exchangeBridgeToken(config.apiKey);
  }
  if (config?.serverBaseUrl) {
    setMeta("bridge.meta.extension", { url: config.serverBaseUrl });
  }
  if (!bridgeToken) {
    throw new Error(t("bridge.error.noKey"));
  }
  const serverConfig = await api("/api/v1/video/config");
  if (!serverConfig.extensionId) {
    throw new Error(t("bridge.error.keyNotConnected"));
  }
  if (serverConfig.extensionId !== config.extensionId) {
    throw new Error(
      t("bridge.error.mismatch", {
        bound: serverConfig.extensionId,
        target: config.extensionId,
      }),
    );
  }
  await configure();
  log(t("bridge.log.auto"));
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await configure();
    showNotice(t("bridge.notice.started"));
  } catch (error) {
    const message = errorText(error);
    setState("bridge.state.failed");
    log(message);
    showNotice(message, true);
  } finally {
    button.disabled = false;
  }
});

extensionInput.value = localStorage.getItem("abm_bridge_extension") || "";
void autoConfigure().catch((error) => {
  const message = errorText(error);
  setState("bridge.state.waiting");
  setMetaRaw(message);
  log(message);
});
