import { formatTime, request } from "./api.js";
import { confirmAction, escapeHtml, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);
let currentUser = null;

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function fillUser(user) {
  currentUser = user;
  setText("wsAccountName", user.displayName);
  setText("wsAccountEmail", user.email);
  setText("wsAccountAvatar", (user.displayName || "U").slice(0, 1));
  setText("wsAccountRole", user.role === "admin" ? t("workspace.adminRole") : t("workspace.userRole"));
  setText("wsAccountPlan", user.planCode === "pro" ? "Pro" : "Free");
  const status = $("wsAccountEmailStatus");
  if (status) {
    status.innerHTML = user.emailVerifiedAt
      ? `<span class="ws-status ws-status-ok">${escapeHtml(t("workspace.emailVerified"))}</span>`
      : `<span class="ws-status ws-status-warn">${escapeHtml(t("workspace.emailUnverified"))}</span>`;
  }
  const verify = $("wsVerifyEmail");
  if (verify) verify.hidden = Boolean(user.emailVerifiedAt);
}

function deviceLabel(userAgent) {
  if (!userAgent) return t("workspace.unknownDevice");
  const browser = /Edg\//.test(userAgent) ? "Edge" : /Chrome\//.test(userAgent) ? "Chrome" : /Safari\//.test(userAgent) ? "Safari" : "Browser";
  const os = /Windows/.test(userAgent) ? "Windows" : /Mac OS X/.test(userAgent) ? "macOS" : /iPhone|iPad/.test(userAgent) ? "iOS" : "Desktop";
  return `${browser} · ${os}`;
}

async function loadSessions() {
  try {
    const result = await request("/api/v1/auth/sessions");
    const items = result.items || [];
    setText("wsSessionSummary", t("workspace.sessionsSummary", { count: items.length }));
    const body = $("wsSessionsBody");
    body.innerHTML = items
      .map(
        (item) => `<tr>
          <td><b>${escapeHtml(deviceLabel(item.userAgent))}</b>${item.ipAddress ? `<small style="display:block;color:var(--muted);margin-top:2px">${escapeHtml(item.ipAddress)}</small>` : ""}</td>
          <td>${escapeHtml(formatTime(item.lastSeenAt))}</td>
          <td class="ws-actions-cell">${item.current ? `<span class="ws-status ws-status-ok">${escapeHtml(t("workspace.current"))}</span>` : `<button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-revoke-session="${item.id}">${escapeHtml(t("workspace.revoke"))}</button>`}</td>
        </tr>`,
      )
      .join("");
    body.querySelectorAll("[data-revoke-session]").forEach((button) => {
      button.addEventListener("click", () => revokeSession(button.dataset.revokeSession));
    });
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

async function revokeSession(id) {
  confirmAction(t("workspace.revokeSessionTitle"), t("workspace.revokeSessionBody"), async () => {
    try {
      await request(`/api/v1/auth/sessions/${id}`, { method: "DELETE" });
      toast(t("workspace.sessionRevoked"));
      await loadSessions();
    } catch {
      toast(t("workspace.updateFailed"), true);
    }
  });
}

async function loadIdentities() {
  try {
    const result = await request("/api/v1/auth/identities");
    const items = result.items || [];
    const providers = result.providers || [];
    setText("wsIdentityCount", t("workspace.identityCount", { count: items.length }));
    const list = $("wsIdentityList");
    list.innerHTML = items.length
      ? items
          .map(
            (item) => `<div class="ws-list-row">
              <span class="ws-provider-mark">${escapeHtml((item.providerName || item.provider || "?").slice(0, 2))}</span>
              <span><b>${escapeHtml(item.providerName || item.provider)}</b><small>${escapeHtml(item.email || "")} · ${escapeHtml(formatTime(item.linkedAt))}</small></span>
              <span class="right"><button class="ws-btn ws-btn-small" type="button" data-unlink="${item.id}">${escapeHtml(t("workspace.unlink"))}</button></span>
            </div>`,
          )
          .join("")
      : `<div class="ws-empty">${escapeHtml(t("workspace.noIdentities"))}</div>`;
    list.querySelectorAll("[data-unlink]").forEach((button) => {
      button.addEventListener("click", () => unlinkIdentity(button.dataset.unlink));
    });
    const bound = new Set(items.map((item) => item.provider));
    $("wsIdentityProviders").innerHTML = providers
      .filter((provider) => !bound.has(provider.id))
      .map(
        (provider) => `<a class="ws-btn ws-btn-small" href="/api/v1/auth/social/${encodeURIComponent(provider.id)}/start?link=1&next=${encodeURIComponent("/console/account")}">${escapeHtml(t("workspace.bind"))} ${escapeHtml(provider.name || provider.id)}</a>`,
      )
      .join("");
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

async function unlinkIdentity(id) {
  confirmAction(t("workspace.unlinkTitle"), t("workspace.unlinkBody"), async () => {
    try {
      await request(`/api/v1/auth/identities/${id}`, { method: "DELETE" });
      toast(t("workspace.identityUnlinked"));
      await loadIdentities();
    } catch {
      toast(t("workspace.updateFailed"), true);
    }
  });
}

$("wsPasswordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await request("/api/v1/auth/password", {
      method: "PATCH",
      body: JSON.stringify({
        current_password: form.get("current_password"),
        new_password: form.get("new_password"),
      }),
    });
    event.target.reset();
    toast(t("workspace.passwordUpdated"));
  } catch {
    toast(t("workspace.passwordFailed"), true);
  }
});

$("wsRevokeOtherSessions").addEventListener("click", () => {
  confirmAction(t("workspace.revokeOthersTitle"), t("workspace.revokeOthersBody"), async () => {
    try {
      await request("/api/v1/auth/sessions/revoke-others", { method: "POST" });
      toast(t("workspace.sessionsRevoked"));
      await loadSessions();
    } catch {
      toast(t("workspace.updateFailed"), true);
    }
  });
});

$("wsVerifyEmail")?.addEventListener("click", async () => {
  try {
    await request("/api/v1/auth/email-verification/request", { method: "POST" });
    toast(t("workspace.verificationSent"));
  } catch {
    toast(t("workspace.updateFailed"), true);
  }
});

$("wsExportAccount").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/v1/auth/account/export", { credentials: "same-origin" });
    if (!response.ok) throw new Error("export failed");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "abm-account-export.json";
    link.click();
    URL.revokeObjectURL(url);
    toast(t("workspace.exported"));
  } catch {
    toast(t("workspace.exportFailed"), true);
  }
});

$("wsDeleteAccount").addEventListener("click", () => {
  const password = window.prompt(t("workspace.deleteAccountPrompt"));
  if (!password) return;
  confirmAction(t("workspace.deleteAccountTitle"), t("workspace.deleteAccountBody"), async () => {
    try {
      await request("/api/v1/auth/account", {
        method: "DELETE",
        body: JSON.stringify({ password }),
      });
      window.location.assign("/");
    } catch {
      toast(t("workspace.deleteAccountFailed"), true);
    }
  });
});

window.wsReady?.then((user) => {
  if (!user) return;
  fillUser(user);
  loadSessions();
  loadIdentities();
  window.addEventListener("workspace:language", () => {
    if (currentUser) fillUser(currentUser);
    loadSessions();
    loadIdentities();
  });
});
