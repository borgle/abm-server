import { request } from "./api.js";
import { confirmAction, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const $ = (id) => document.getElementById(id);

async function load() {
  try {
    const system = await request("/api/v1/admin/system");
    $("wsSysRegistration").checked = Boolean(system.registrationRequireApproval);
    $("wsSysCreation").checked = Boolean(system.enabled);
    $("wsSysByok").checked = Boolean(system.byokEnabled);
    const status = $("wsCreationStatus");
    if (status) {
      status.textContent = system.enabled ? t("workspace.enabled") : t("workspace.disabled");
      status.className = `ws-status ${system.enabled ? "ws-status-ok" : "ws-status-warn"}`;
    }
    $("wsSysRetention").value = String(system.retentionDays ?? 30);
    $("wsSysTrash").value = String(system.trashDays ?? 10);
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

async function save() {
  try {
    await request("/api/v1/admin/system", {
      method: "PATCH",
      body: JSON.stringify({
        registration_require_approval: $("wsSysRegistration").checked,
        enabled: $("wsSysCreation").checked,
        byok_enabled: $("wsSysByok").checked,
        retention_days: Number($("wsSysRetention").value) || 30,
        trash_days: Number($("wsSysTrash").value) || 10,
      }),
    });
    toast(t("workspace.configSaved"));
    await load();
  } catch {
    toast(t("workspace.updateFailed"), true);
  }
}

$("wsSaveSystem").addEventListener("click", save);
$("wsDisableCreation").addEventListener("click", () => {
  confirmAction(t("workspace.disableCreationTitle"), t("workspace.disableCreationBody"), async () => {
    $("wsSysCreation").checked = false;
    await save();
  });
});
$("wsRotateKey").addEventListener("click", () => {
  confirmAction(t("workspace.rotateKeyTitle"), t("workspace.rotateKeyBody"), () => {
    toast(t("workspace.rotateKeyUnavailable"));
  });
});

window.wsReady?.then((user) => {
  if (!user) return;
  load();
  window.addEventListener("workspace:language", () => load());
});
