import { accountError, initAccountPage, t } from "./account-i18n.js";
import { request, showNotice } from "./api.js";

const SCOPE_KEYS = {
  browser: "consent.scope.browser",
  "account:read": "consent.scope.accountRead",
  "account:write": "consent.scope.accountWrite",
};

function translateScopes() {
  document.querySelectorAll("[data-scope]").forEach((element) => {
    const key = SCOPE_KEYS[element.dataset.scope];
    if (key) {
      element.textContent = t(key);
    }
  });
}

function translateConnections() {
  document.querySelectorAll("[data-conn-name]").forEach((element) => {
    const online = element.dataset.connOnline === "1";
    const status = t(online ? "consent.online" : "consent.offline");
    element.textContent =
      element.tagName === "OPTION"
        ? `${element.dataset.connName} · ${status}`
        : `${element.dataset.connName} · ${element.dataset.connPrefix} · ${status}`;
  });
}

initAccountPage({
  titleKey: "consent.pageTitle",
  onChange() {
    translateScopes();
    translateConnections();
  },
});

const form = document.getElementById("consent-form");

if (form) {
  const connectionSection = document.getElementById("connection-section");
  const modeInputs = connectionSection?.querySelectorAll('input[name="connectionMode"]') || [];
  const pinnedSelect = document.getElementById("pinned-connection");
  const poolOptions = document.getElementById("pool-connections");
  const hasConnections = connectionSection?.dataset.connectionCount !== "0";

  function currentMode() {
    return connectionSection?.querySelector('input[name="connectionMode"]:checked')?.value || "auto";
  }

  function syncConnectionMode() {
    const mode = currentMode();
    if (poolOptions) {
      poolOptions.hidden = mode !== "pool";
    }
    if (pinnedSelect) {
      pinnedSelect.disabled = mode !== "pinned";
    }
  }

  modeInputs.forEach((input) => input.addEventListener("change", syncConnectionMode));
  syncConnectionMode();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const decision = event.submitter?.value === "deny" ? "deny" : "approve";
    const requestId = form.dataset.requestId;
    let connectionMode = "auto";
    let connectionIds = [];

    if (decision === "approve" && hasConnections) {
      connectionMode = currentMode();
      if (connectionMode === "pinned" && pinnedSelect?.value) {
        connectionIds = [pinnedSelect.value];
      } else if (connectionMode === "pool") {
        connectionIds = Array.from(
          connectionSection?.querySelectorAll('input[name="connectionId"]:checked') || [],
          (input) => input.value,
        );
        if (connectionIds.length === 0) {
          showNotice(t("consent.selectConnection"), true);
          return;
        }
      }
    }

    const buttons = form.querySelectorAll("button");
    buttons.forEach((button) => {
      button.disabled = true;
    });
    try {
      const result = await request("/oauth/authorize", {
        method: "POST",
        body: JSON.stringify({ requestId, decision, connectionMode, connectionIds }),
      });
      window.location.assign(result.redirect);
    } catch (error) {
      showNotice(accountError(error), true);
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  });
}
