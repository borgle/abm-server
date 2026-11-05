import { logout, requireUser } from "./api.js";
import { bindShell, toast } from "./ui.js";
import { initWorkspacePage, t } from "./workspace-i18n.js";

const body = document.body;
const app = body.dataset.app || "console";
const section = body.dataset.section || "overview";

/**
 * Nested module imports ("./workspace-i18n.js") keep the bare URL, so a browser
 * that cached the module before a deploy can keep rendering raw i18n keys.
 * Detect that once per session, refresh the module cache and reload.
 */
const I18N_RELOAD_FLAG = "abm.i18n.reloaded";
const SHARED_MODULES = [
  "api.js",
  "ui.js",
  "i18n.js",
  "workspace-i18n.js",
  "workspace-admin-common.js",
  "creation-common.js",
];
// Keys that only exist in the current dictionary. If the cached module predates
// them, `t` returns the key itself.
const I18N_PROBE_KEYS = ["workspace.generateDraft", "workspace.aiTitle"];

function hasStaleTranslations() {
  if (I18N_PROBE_KEYS.some((key) => t(key) === key)) return true;
  return [...document.querySelectorAll("[data-i18n]")].some(
    (node) => node.dataset.i18n && node.textContent.trim() === node.dataset.i18n,
  );
}

async function refreshModuleCache() {
  const scripts = [...document.querySelectorAll('script[type="module"][src]')].map(
    (node) => node.src,
  );
  const shared = SHARED_MODULES.map((name) => new URL(`/static/${name}`, location.origin).href);
  await Promise.all(
    [...new Set([...scripts, ...shared])].map((url) =>
      fetch(url, { cache: "reload" }).catch(() => null),
    ),
  );
}

const PAGES = {
  console: [
    ["overview", "/console/overview", "workspace.navOverview"],
    ["connections", "/console/connections", "workspace.navConnections"],
    ["usage", "/console/usage", "workspace.navUsage"],
    ["account", "/console/account", "workspace.navAccountSecurity"],
    ["help", "/console/help", "workspace.navHelp"],
  ],
  admin: [
    ["overview", "/admin/overview", "workspace.navAdminOverview"],
    ["users", "/admin/users", "workspace.navUsers"],
    ["approvals", "/admin/approvals", "workspace.navApprovals"],
    ["plans", "/admin/plans", "workspace.navPlans"],
    ["audit", "/admin/audit", "workspace.navAudit"],
    ["system", "/admin/system", "workspace.navSystem"],
    ["config", "/admin/config", "workspace.navConfig"],
  ],
  creation: [
    ["overview", "/creation/overview", "workspace.creationOverview"],
    ["radar", "/creation/radar", "workspace.creationRadar"],
    ["library", "/creation/library", "workspace.creationLibrary"],
    ["studio", "/creation/studio", "workspace.creationStudio"],
    ["templates", "/creation/templates", "workspace.creationTemplates"],
    ["assets", "/creation/assets", "workspace.creationAssets"],
    ["trash", "/creation/trash", "workspace.creationTrash"],
    ["publish", "/creation/publish", "workspace.creationPublish"],
  ],
};

function setupCommandPalette(isAdmin) {
  const input = document.getElementById("wsCommandInput");
  const list = document.getElementById("wsCommandList");
  const root = document.getElementById("wsCommand");
  if (!input || !list || !root) return;

  const commands = PAGES[app].map(([key, path, labelKey]) => ({
    label: t(labelKey),
    hint: t("workspace.page." + key),
    run: () => window.location.assign(path),
  }));
  if (isAdmin && app === "console") {
    commands.push({
      label: t("workspace.appAdmin"),
      hint: "/admin/overview",
      run: () => window.location.assign("/admin/overview"),
    });
  }

  let index = 0;
  let filtered = commands;

  function render(query = "") {
    const needle = query.trim().toLowerCase();
    filtered = commands.filter((item) => (item.label + item.hint).toLowerCase().includes(needle));
    index = 0;
    list.replaceChildren();
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "ws-empty";
      empty.textContent = t("workspace.loading");
      list.appendChild(empty);
      return;
    }
    filtered.forEach((item, itemIndex) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `ws-command-item${itemIndex === 0 ? " on" : ""}`;
      button.textContent = item.label;
      button.addEventListener("click", () => {
        root.hidden = true;
        item.run();
      });
      list.appendChild(button);
    });
  }

  function open() {
    root.hidden = false;
    input.value = "";
    render("");
    input.focus();
  }

  document.getElementById("wsCommandTrigger")?.addEventListener("click", open);
  input.addEventListener("input", () => render(input.value));
  root.addEventListener("click", (event) => {
    if (event.target === root) root.hidden = true;
  });
  document.addEventListener("keydown", (event) => {
    const isMac = navigator.platform.toLowerCase().includes("mac");
    if ((isMac ? event.metaKey : event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      open();
      return;
    }
    if (root.hidden) return;
    if (event.key === "Escape") {
      root.hidden = true;
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      index = (index + (event.key === "ArrowDown" ? 1 : -1) + filtered.length) % Math.max(1, filtered.length);
      list.querySelectorAll(".ws-command-item").forEach((item, itemIndex) => {
        item.classList.toggle("on", itemIndex === index);
      });
    }
    if (event.key === "Enter") {
      event.preventDefault();
      filtered[index]?.run();
      root.hidden = true;
    }
  });
}

function showSocialNotice() {
  const params = new URLSearchParams(window.location.search);
  const social = params.get("social");
  if (!social) return;
  const key = social === "linked" ? "workspace.socialLinked" : "workspace.socialLogin";
  toast(t(key));
  params.delete("social");
  const query = params.toString();
  window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

async function boot() {
  initWorkspacePage({ titleKey: body.dataset.titleKey });
  if (hasStaleTranslations() && !sessionStorage.getItem(I18N_RELOAD_FLAG)) {
    sessionStorage.setItem(I18N_RELOAD_FLAG, "1");
    await refreshModuleCache();
    location.reload();
    return null;
  }
  sessionStorage.removeItem(I18N_RELOAD_FLAG);
  bindShell();
  const user = await requireUser();
  if (!user) return null;
  if (app === "admin" && user.role !== "admin") {
    window.location.assign("/console/overview");
    return null;
  }
  const initial = (user.displayName || "U").slice(0, 1);
  document.querySelectorAll(".ws-user-mini .ws-avatar, .ws-top-avatar").forEach((node) => {
    node.textContent = initial;
    node.title = user.displayName || "";
  });
  setupCommandPalette(user.role === "admin");
  document.getElementById("wsLogout")?.addEventListener("click", () => logout());
  window.__WS_USER__ = user;
  showSocialNotice();
  window.dispatchEvent(new CustomEvent("ws:ready", { detail: user }));
  return user;
}

window.wsReady = boot();
