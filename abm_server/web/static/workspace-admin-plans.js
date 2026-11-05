import { request } from "./api.js";
import { confirmAction, escapeHtml, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
const singleEdition = document.body.dataset.edition === "single";
const state = { providers: [], plans: {}, system: null };

function planCard(plan) {
  return document.querySelector(`[data-plan="${plan}"]`);
}

function providerOptions(selected) {
  return (
    `<option value="">${escapeHtml(t("workspace.notBound"))}</option>` +
    state.providers
      .map(
        (provider) =>
          `<option value="${escapeHtml(provider.id)}" ${provider.id === selected ? "selected" : ""}>${escapeHtml(provider.name)}</option>`,
      )
      .join("")
  );
}

function fillPlan(plan, config) {
  const card = planCard(plan);
  if (!card) return;
  const provider = card.querySelector('[data-field="provider"]');
  if (provider) provider.innerHTML = providerOptions(config.providerId || "");
  const imageProvider = card.querySelector('[data-field="imageProvider"]');
  if (imageProvider) imageProvider.innerHTML = providerOptions(config.imageProviderId || "");
  const set = (field, value) => {
    const input = card.querySelector(`[data-field="${field}"]`);
    if (input) input.value = value;
  };
  set("researchPages", config.pagesPerMonth ?? 0);
  set("tokens", config.tokenQuotaMonth ?? 0);
  set("generations", config.generationsPerDay ?? 0);
  set("storage", Math.round((config.storageBytes || 0) / 1024 / 1024));
  set("upload", Math.round((config.maxUploadBytes || 0) / 1024 / 1024));
  set("model", config.model || "");
  set("fallback", config.fallbackModel || "");
  set("imageModel", config.imageModel || "");
  set("imageGenerations", config.imageGenerationsPerDay ?? 0);
  set("imageMaxN", config.imageMaxN ?? 4);
  set("browserConnections", config.browserConnections ?? 2);
  set("browserSessions", config.browserSessions ?? 1);
  set("reservedSlots", config.reservedPrioritySlots ?? 0);
  const status = card.querySelector("[data-plan-status]");
  const bound = Boolean(config.providerId && config.model);
  if (status) {
    status.textContent = bound ? t("workspace.bound") : t("workspace.notBound");
    status.className = `ws-status ${bound ? "ws-status-ok" : "ws-status-warn"}`;
  }
}

function renderProviders() {
  const list = $("wsProvidersList");
  if (!state.providers.length) {
    list.innerHTML = `<div class="ws-empty">${escapeHtml(t("workspace.noProviders"))}</div>`;
    return;
  }
  list.innerHTML = state.providers
    .map(
      (provider) => `
      <div class="ws-provider-row">
        <span class="ws-provider-mark">${escapeHtml((provider.name || "?").slice(0, 2).toUpperCase())}</span>
        <span><b>${escapeHtml(provider.name)}</b><small>${escapeHtml(provider.baseUrl)} · ${escapeHtml(provider.apiKeyLast4 ? "sk-…" + provider.apiKeyLast4 : t("workspace.noKey"))}</small></span>
        <span class="ws-provider-actions">
          <span class="ws-status ${provider.status === "ok" ? "ws-status-ok" : provider.status === "invalid" ? "ws-status-bad" : "ws-status-warn"}">${escapeHtml(provider.status === "ok" ? t("workspace.available") : provider.status === "invalid" ? t("workspace.invalid") : t("workspace.unverified"))}</span>
          <button class="ws-btn ws-btn-small" type="button" data-test-provider="${provider.id}">${escapeHtml(t("workspace.test"))}</button>
          <button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-delete-provider="${provider.id}">${escapeHtml(t("workspace.delete"))}</button>
        </span>
      </div>`,
    )
    .join("");
  list.querySelectorAll("[data-test-provider]").forEach((button) => {
    button.addEventListener("click", () => testProvider(button.dataset.testProvider));
  });
  list.querySelectorAll("[data-delete-provider]").forEach((button) => {
    button.addEventListener("click", () => {
      const provider = state.providers.find((item) => item.id === button.dataset.deleteProvider);
      if (!provider) return;
      confirmAction(t("workspace.deleteProviderTitle"), t("workspace.deleteProviderBody", { name: provider.name }), () => deleteProvider(provider));
    });
  });
}

async function load() {
  try {
    const [plans, system] = await Promise.all([
      singleEdition
        ? request("/api/v1/admin/local-model")
        : request("/api/v1/admin/plans"),
      request("/api/v1/admin/system"),
    ]);
    if (singleEdition) {
      state.providers = plans.providers || [];
      state.plans = { free: plans.local || {}, pro: {} };
    } else {
      state.providers = plans.providers || [];
      state.plans = plans.plans || {};
    }
    state.system = system;
    fillPlan("free", state.plans.free || {});
    if (!singleEdition) fillPlan("pro", state.plans.pro || {});
    renderProviders();
    $("wsPlanRetention").textContent = `${system.retentionDays ?? 30} 天`;
    $("wsPlanTrash").textContent = `${system.trashDays ?? 10} 天`;
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

function planPayload(plan) {
  const card = planCard(plan);
  const value = (field) => card.querySelector(`[data-field="${field}"]`)?.value ?? "";
  return {
    provider_id: value("provider"),
    model: value("model").trim(),
    fallback_model: value("fallback").trim(),
    token_quota_month: Number(value("tokens")) || 0,
    generations_per_day: Number(value("generations")) || 0,
    pages_per_month: Number(value("researchPages")) || 0,
    storage_bytes: (Number(value("storage")) || 0) * 1024 * 1024,
    max_upload_bytes: (Number(value("upload")) || 0) * 1024 * 1024,
    image_provider_id: value("imageProvider"),
    image_model: value("imageModel").trim(),
    image_generations_per_day: Number(value("imageGenerations")) || 0,
    image_max_n: Number(value("imageMaxN")) || 1,
    browser_connections: Number(value("browserConnections")) || 1,
    browser_sessions: Number(value("browserSessions")) || 1,
    reserved_priority_slots: Number(value("reservedSlots")) || 0,
  };
}

async function savePlans() {
  try {
    if (singleEdition) {
      const card = planCard("free");
      const value = (field) => card.querySelector(`[data-field="${field}"]`)?.value ?? "";
      await request("/api/v1/admin/local-model", {
        method: "PUT",
        body: JSON.stringify({
          provider_id: value("provider"),
          model: value("model").trim(),
          fallback_model: value("fallback").trim(),
          image_provider_id: value("imageProvider"),
          image_model: value("imageModel").trim(),
          image_max_n: Number(value("imageMaxN")) || 1,
        }),
      });
    } else {
      await Promise.all([
        request("/api/v1/admin/plans/free", {
          method: "PUT",
          body: JSON.stringify(planPayload("free")),
        }),
        request("/api/v1/admin/plans/pro", {
          method: "PUT",
          body: JSON.stringify(planPayload("pro")),
        }),
      ]);
    }
    toast(t("workspace.configSaved"));
    await load();
  } catch {
    toast(t("workspace.updateFailed"), true);
  }
}

async function testProvider(providerId) {
  try {
    const result = await request(`/api/v1/admin/creation/providers/${providerId}/test`, {
      method: "POST",
    });
    toast(result.ok ? t("workspace.testOk") : t("workspace.testFailed"));
    await load();
  } catch {
    toast(t("workspace.testFailed"), true);
  }
}

async function testAll() {
  for (const provider of state.providers) {
    await testProvider(provider.id);
  }
}

async function deleteProvider(provider) {
  try {
    await request(`/api/v1/admin/creation/providers/${provider.id}`, { method: "DELETE" });
    toast(t("workspace.providerDeleted"));
    await load();
  } catch {
    toast(t("workspace.providerDeleteFailed"), true);
  }
}

function openProviderModal() {
  const wrap = $("wsModalWrap");
  const modal = $("wsModal");
  modal.innerHTML = `
    <div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.addProvider"))}</h2>
      <p>${escapeHtml(t("workspace.addProviderLead"))}</p>
      <div class="ws-form-grid" style="grid-template-columns: 1fr">
        <label class="ws-field">${escapeHtml(t("workspace.providerName"))}<input class="ws-input" id="npName" placeholder="DeepSeek 官方" /></label>
        <label class="ws-field">Base URL<input class="ws-input" id="npBase" placeholder="https://api.deepseek.com/v1" /></label>
        <label class="ws-field">API Key<input class="ws-input" id="npKey" type="password" placeholder="sk-…" /></label>
      </div>
      <div class="ws-actions" style="justify-content: flex-end; margin-top: 14px">
        <button class="ws-btn" type="button" data-modal-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" id="npSave">${escapeHtml(t("workspace.save"))}</button>
      </div>
    </div>`;
  modal.setAttribute("aria-label", t("workspace.addProvider"));
  wrap.classList.add("show");
  modal.onclick = (event) => {
    if (event.target.closest('[data-modal-action="cancel"]')) {
      wrap.classList.remove("show");
      modal.innerHTML = "";
    }
  };
  $("npSave").addEventListener("click", async () => {
    const name = $("npName").value.trim();
    const baseUrl = $("npBase").value.trim();
    const apiKey = $("npKey").value.trim();
    if (!name || !baseUrl || !apiKey) {
      toast(t("workspace.requiredFields"), true);
      return;
    }
    try {
      await request("/api/v1/admin/creation/providers", {
        method: "POST",
        body: JSON.stringify({ name, base_url: baseUrl, api_key: apiKey }),
      });
      wrap.classList.remove("show");
      modal.innerHTML = "";
      toast(t("workspace.providerSaved"));
      await load();
    } catch {
      toast(t("workspace.providerSaveFailed"), true);
    }
  });
}

$("wsSavePlans").addEventListener("click", savePlans);
$("wsTestAllProviders").addEventListener("click", testAll);
$("wsAddProvider").addEventListener("click", openProviderModal);

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", () => load());
});
