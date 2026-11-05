import { request } from "./api.js";
import { escapeHtml, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
let templates = [];
let categories = [];
let activeCategory = "";

const PLATFORM_KEYS = {
  master: "workspace.platform.master",
  xiaohongshu: "workspace.platform.xiaohongshu",
  wechat: "workspace.platform.wechat",
  shipinhao: "workspace.platform.shipinhao",
  zhihu: "workspace.platform.zhihu",
};

function platformBadge(platforms) {
  const labels = (platforms || []).map((platform) => {
    const key = PLATFORM_KEYS[platform];
    const value = key ? t(key) : platform;
    return value === key ? platform : value;
  });
  if (!labels.length) return "";
  return labels.length > 2
    ? `${labels.slice(0, 2).join(" ? ")} +${labels.length - 2}`
    : labels.join(" ? ");
}

function renderCategories() {
  const bar = $("templateCategories");
  const options = [{ id: "", name: t("workspace.allCategories") }, ...categories];
  bar.innerHTML = options
    .map(
      (category) =>
        `<button type="button" class="ws-chip${activeCategory === category.id ? " on" : ""}" data-category="${category.id}" aria-pressed="${activeCategory === category.id}">${escapeHtml(category.name)}</button>`,
    )
    .join("");
  bar.querySelectorAll("[data-category]").forEach((button) => {
    button.addEventListener("click", () => {
      activeCategory = button.dataset.category;
      renderCategories();
      renderGrid();
    });
  });
}

function actionHref(template) {
  const action = template.action || {};
  if (action.kind === "radar") {
    const params = new URLSearchParams();
    params.set("keywords", (action.keywords || []).join(","));
    params.set("engines", (action.engines || []).join(","));
    params.set("depth", action.depth || "standard");
    return `/creation/radar?${params.toString()}`;
  }
  if (action.kind === "asset") {
    return `/creation/assets?template=${encodeURIComponent(template.id)}`;
  }
  if (action.kind === "library") return "/creation/library";
  return "/creation/assets";
}

function renderGrid() {
  const grid = $("templateGrid");
  const list = templates.filter(
    (template) => !activeCategory || template.category === activeCategory,
  );
  if (!list.length) {
    grid.innerHTML = `<div class="ws-empty">${t("workspace.noTemplates")}</div>`;
    return;
  }
  grid.innerHTML = list
    .map(
      (template) => `<article class="ws-card ws-card-pad ws-template-card">
        <div class="ws-card-head"><div><p class="ws-eyebrow">${escapeHtml(template.category.toUpperCase())}</p><h2>${escapeHtml(template.name)}</h2></div><span class="ws-pill">${escapeHtml(platformBadge(template.platforms))}</span></div>
        <p>${escapeHtml(template.description)}</p>
        <ol class="ws-template-steps">${template.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
        <div class="ws-actions"><a class="ws-btn ws-btn-primary" href="${actionHref(template)}">${t("workspace.useTemplate")}</a></div>
      </article>`,
    )
    .join("");
}

async function load() {
  try {
    const result = await request("/api/v1/creation/templates");
    templates = result.items || [];
    categories = result.categories || [];
    renderCategories();
    renderGrid();
  } catch (error) {
    $("templateGrid").innerHTML = `<div class="ws-empty">${t("workspace.loadFailed")}</div>`;
    toast(error.message || t("workspace.loadFailed"), true);
  }
}

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", () => {
    renderCategories();
    renderGrid();
  });
});
