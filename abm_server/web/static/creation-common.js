import { request } from "./api.js";
import { closeModal, confirmAction, openModal, toast } from "./ui.js";
import { t } from "./workspace-i18n.js";

const select = document.getElementById("creationProjectSelect");
const ALL_PROJECTS = "__all__";
let projects = [];

async function loadProjects() {
  try {
    const result = await request("/api/v1/creation/projects");
    projects = result.items || [];
    render();
  } catch {
    toast(t("workspace.loadFailed"), true);
  }
}

function selectedProject() {
  const saved = localStorage.getItem("abm.creation.project") || "";
  if (saved === ALL_PROJECTS) return ALL_PROJECTS;
  if (projects.some((project) => project.id === saved)) return saved;
  return projects[0]?.id || "";
}

function render() {
  if (!select) return;
  const selected = selectedProject();
  select.innerHTML =
    `<option value="${ALL_PROJECTS}" ${selected === ALL_PROJECTS ? "selected" : ""}>${escapeHtml(t("workspace.allProjects"))}</option>` +
    projects
      .map(
        (project) =>
          `<option value="${project.id}" ${project.id === selected ? "selected" : ""}>${escapeHtml(project.title)}</option>`,
      )
      .join("") +
    `<option value="__new__">＋ ${escapeHtml(t("workspace.newProject"))}</option>`;
  select.value = selected || "__new__";
  window.creationProjectId = selected && selected !== ALL_PROJECTS ? selected : null;
  window.creationProjects = projects;
  localStorage.setItem("abm.creation.project", selected);
  window.dispatchEvent(new CustomEvent("creation:projects", { detail: projects }));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function createProject(title) {
  const result = await request("/api/v1/creation/projects", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  localStorage.setItem("abm.creation.project", result.project.id);
  toast(t("workspace.projectCreated"));
  await loadProjects();
  window.dispatchEvent(new CustomEvent("creation:project", { detail: result.project.id }));
}

select?.addEventListener("change", async () => {
  if (select.value === "__new__") {
    const title = window.prompt(t("workspace.projectPrompt"));
    if (!title) {
      render();
      return;
    }
    try {
      await createProject(title);
    } catch {
      toast(t("workspace.projectCreateFailed"), true);
    }
    return;
  }
  if (select.value === ALL_PROJECTS) {
    window.creationProjectId = null;
    localStorage.setItem("abm.creation.project", ALL_PROJECTS);
    window.dispatchEvent(new CustomEvent("creation:project", { detail: null }));
    return;
  }
  window.creationProjectId = select.value || null;
  localStorage.setItem("abm.creation.project", select.value);
  window.dispatchEvent(new CustomEvent("creation:project", { detail: select.value }));
});

export function openProjectManager() {
  const rows = projects.length
    ? projects
        .map(
          (project) => `<div class="ws-project-row" data-project="${project.id}">
            <div>
              <input class="ws-input" value="${escapeHtml(project.title)}" data-title aria-label="${escapeHtml(t("workspace.projectName"))}" />
              <small>${escapeHtml(t("workspace.projectAssetCount", { count: project.assetCount || 0 }))}</small>
            </div>
            <button class="ws-btn ws-btn-small" type="button" data-save>${t("workspace.save")}</button>
            <button class="ws-btn ws-btn-small ws-btn-danger" type="button" data-archive>${t("workspace.archiveProject")}</button>
          </div>`,
        )
        .join("")
    : `<div class="ws-empty">${t("workspace.noProjects")}</div>`;

  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${t("workspace.manageProjects")}</h2>
      <p>${t("workspace.manageProjectsLead")}</p>
      <div class="ws-project-list">${rows}</div>
      <div class="ws-actions" style="justify-content:space-between;margin-top:14px">
        <button class="ws-btn" type="button" data-create>＋ ${t("workspace.newProject")}</button>
        <button class="ws-btn" type="button" data-close>${t("workspace.close")}</button>
      </div>
    </div>`,
    t("workspace.manageProjects"),
  );

  modal.onclick = async (event) => {
    const row = event.target.closest("[data-project]");
    if (event.target.closest("[data-close]")) {
      closeModal();
      return;
    }
    if (event.target.closest("[data-create]")) {
      const title = window.prompt(t("workspace.projectPrompt"));
      if (!title) return;
      try {
        await createProject(title);
        closeModal();
        openProjectManager();
      } catch {
        toast(t("workspace.projectCreateFailed"), true);
      }
      return;
    }
    if (!row) return;
    const projectId = row.dataset.project;
    const title = row.querySelector("[data-title]").value.trim();
    if (event.target.closest("[data-save]")) {
      if (!title) return toast(t("workspace.projectTitleRequired"), true);
      try {
        await request(`/api/v1/creation/projects/${projectId}`, {
          method: "PATCH",
          body: JSON.stringify({ title }),
        });
        toast(t("workspace.projectRenamed"));
        await loadProjects();
        if (window.creationProjectId === projectId) {
          window.dispatchEvent(new CustomEvent("creation:project", { detail: projectId }));
        }
      } catch (error) {
        toast(error.message || t("workspace.saveFailed"), true);
      }
    }
    if (event.target.closest("[data-archive]")) {
      const project = projects.find((item) => item.id === projectId);
      confirmAction(
        t("workspace.archiveProject"),
        t("workspace.archiveProjectConfirm", { title: project?.title || "" }),
        async () => {
          try {
            await request(`/api/v1/creation/projects/${projectId}`, { method: "DELETE" });
            if (window.creationProjectId === projectId) {
              localStorage.removeItem("abm.creation.project");
              window.creationProjectId = null;
            }
            toast(t("workspace.projectArchived"));
            await loadProjects();
            window.dispatchEvent(
              new CustomEvent("creation:project", { detail: window.creationProjectId }),
            );
            openProjectManager();
          } catch (error) {
            toast(error.message || t("workspace.actionFailed"), true);
          }
        },
      );
    }
  };
}

document.getElementById("creationProjectManage")?.addEventListener("click", openProjectManager);

window.creationProjectsReady = window.wsReady.then(async (user) => {
  if (!user) return [];
  await loadProjects();
  return projects;
});

export function openCreateAsset(prefill = {}) {
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(t("workspace.createAsset"))}</h2>
      <p>${escapeHtml(t("workspace.createAssetLead"))}</p>
      <label class="ws-field">${escapeHtml(t("workspace.assetTitle"))}<input class="ws-input" id="creationNewTitle" placeholder="${escapeHtml(t("workspace.untitled"))}" value="${escapeHtml(prefill.title || "")}" /></label>
      <label class="ws-field" style="margin-top:9px">${escapeHtml(t("workspace.platformLabel"))}
        <select class="ws-select" id="creationNewPlatform">
          <option value="master">主稿</option><option value="xiaohongshu">小红书</option>
          <option value="wechat">公众号</option><option value="shipinhao">视频号</option><option value="zhihu">知乎</option>
        </select>
      </label>
      <div class="ws-actions" style="justify-content:flex-end;margin-top:14px">
        <button class="ws-btn" type="button" data-modal-action="cancel">${escapeHtml(t("workspace.cancel"))}</button>
        <button class="ws-btn ws-btn-primary" type="button" id="creationNewConfirm">${escapeHtml(t("workspace.create"))}</button>
      </div>
    </div>`,
    t("workspace.createAsset"),
  );
  const platformSelect = document.getElementById("creationNewPlatform");
  if (prefill.platform) platformSelect.value = prefill.platform;
  modal.onclick = (event) => {
    if (event.target.closest('[data-modal-action="cancel"]')) closeModal();
  };
  document.getElementById("creationNewConfirm").addEventListener("click", async () => {
    const title = document.getElementById("creationNewTitle").value.trim();
    if (!title) return toast(t("workspace.assetTitleRequired"), true);
    try {
      const result = await request("/api/v1/creation/assets", {
        method: "POST",
        body: JSON.stringify({
          title,
          platform: document.getElementById("creationNewPlatform").value,
          project_id: window.creationProjectId || null,
        }),
      });
      closeModal();
      window.location.assign(`/creation/studio?asset=${encodeURIComponent(result.asset.id)}`);
    } catch {
      toast(t("workspace.assetCreateFailed"), true);
    }
  });
}
