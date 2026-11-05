import { request } from "./api.js";
import { escapeHtml, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
let groups = [];
let initialValues = {};

/** Prefer the UI dictionary, fall back to the server-provided copy. */
const tr = (key, fallback) => {
  const value = t(key);
  return value === key ? fallback : value;
};

function control(item) {
  const id = `config-${item.key}`;
  const value = item.value;
  if (item.type === "bool") {
    return `<label class="ws-config-switch"><input type="checkbox" id="${id}" data-key="${item.key}" ${value ? "checked" : ""}/><span>${value ? t("workspace.configOn") : t("workspace.configOff")}</span></label>`;
  }
  if (item.options?.length) {
    return `<select class="ws-select" id="${id}" data-key="${item.key}">${item.options
      .map((option) => `<option value="${escapeHtml(option)}" ${option === value ? "selected" : ""}>${escapeHtml(option)}</option>`)
      .join("")}</select>`;
  }
  if (item.type === "int") {
    return `<input class="ws-input" id="${id}" data-key="${item.key}" type="number" value="${Number(value)}" ${item.minimum != null ? `min="${item.minimum}"` : ""} ${item.maximum != null ? `max="${item.maximum}"` : ""}/>`;
  }
  return `<input class="ws-input" id="${id}" data-key="${item.key}" value="${escapeHtml(value ?? "")}"/>`;
}

function currentValues() {
  const values = {};
  document.querySelectorAll("[data-key]").forEach((input) => {
    const key = input.dataset.key;
    if (input.type === "checkbox") values[key] = input.checked;
    else if (input.type === "number") values[key] = Number(input.value);
    else values[key] = input.value;
  });
  return values;
}

function render({ preserveEdits = false } = {}) {
  const pending = preserveEdits ? currentValues() : null;
  initialValues = {};
  groups.forEach((group) => {
    group.items.forEach((item) => {
      initialValues[item.key] = item.value;
    });
  });
  $("configGroups").innerHTML = groups
    .map(
      (group) => `<article class="ws-card ws-card-pad">
        <div class="ws-card-head"><div><h2>${escapeHtml(tr(`config.group.${group.id}`, group.label))}</h2><p>${group.items.length} ${t("workspace.configItems")}</p></div></div>
        <div class="ws-config-list">
          ${group.items
            .map(
              (item) => `<div class="ws-config-row">
                <div><b>${escapeHtml(tr(`config.item.${item.key}.label`, item.label))}</b><small>${escapeHtml(tr(`config.item.${item.key}.description`, item.description || item.key))}</small>
                  <span class="ws-config-tags"><code>${escapeHtml(item.key)}</code>${item.source === "database" ? `<em>${t("workspace.configOverridden")}</em>` : ""}${item.restartRequired ? `<em>${t("workspace.configRestart")}</em>` : ""}</span>
                </div>
                <div class="ws-config-control">${control(item)}</div>
              </div>`,
            )
            .join("")}
        </div>
      </article>`,
    )
    .join("");

  if (!pending) return;
  document.querySelectorAll("[data-key]").forEach((input) => {
    const key = input.dataset.key;
    if (!(key in pending)) return;
    if (input.type === "checkbox") {
      input.checked = Boolean(pending[key]);
      const label = input.closest(".ws-config-switch")?.querySelector("span");
      if (label) label.textContent = input.checked ? t("workspace.configOn") : t("workspace.configOff");
    } else {
      input.value = pending[key];
    }
  });
}

async function load() {
  try {
    const result = await request("/api/v1/admin/system/config");
    groups = result.groups || [];
    render();
  } catch (error) {
    $("configGroups").innerHTML = `<div class="ws-empty">${t("workspace.loadFailed")}</div>`;
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

function collect() {
  const values = {};
  document.querySelectorAll("[data-key]").forEach((input) => {
    const key = input.dataset.key;
    let value;
    if (input.type === "checkbox") value = input.checked;
    else if (input.type === "number") value = Number(input.value);
    else value = input.value;
    if (value !== initialValues[key]) values[key] = value;
  });
  return values;
}

async function save() {
  const values = collect();
  if (!Object.keys(values).length) {
    toast(t("workspace.configUnchanged"));
    return;
  }
  const button = $("configSave");
  button.disabled = true;
  try {
    const result = await request("/api/v1/admin/system/config", {
      method: "PATCH",
      body: JSON.stringify({ values }),
    });
    groups = result.groups || [];
    render();
    toast(t("workspace.configSaved"));
  } catch (error) {
    toast(error.message || t("workspace.saveFailed"), true);
  } finally {
    button.disabled = false;
  }
}

async function importFile(file) {
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    const values = payload.values || payload;
    const result = await request("/api/v1/admin/system/config/import", {
      method: "POST",
      body: JSON.stringify({ values, mode: "merge" }),
    });
    groups = result.groups || [];
    render();
    toast(t("workspace.configImported"));
  } catch (error) {
    toast(error.message || t("workspace.configImportFailed"), true);
  }
}

$("configSave").addEventListener("click", save);
$("configImportTrigger").addEventListener("click", () => $("configImportFile").click());
$("configImportFile").addEventListener("change", (event) => {
  importFile(event.target.files?.[0]);
  event.target.value = "";
});

load();
window.addEventListener("workspace:language", () => render({ preserveEdits: true }));
