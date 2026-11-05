const drawer = () => document.getElementById("wsDrawer");
const drawerBody = () => document.getElementById("wsDrawerBody");
const drawerFoot = () => document.getElementById("wsDrawerFoot");
const scrim = () => document.getElementById("wsScrim");

export function toast(message, isError = false) {
  const el = document.getElementById("wsToast");
  if (!el) return;
  document.getElementById("wsToastText").textContent = message;
  el.classList.toggle("error", Boolean(isError));
  el.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.remove("show"), 2800);
}

export function openDrawer({ title, sub = "", body = "", footer = "", onAction } = {}) {
  document.getElementById("wsDrawerTitle").textContent = title || "";
  document.getElementById("wsDrawerSub").textContent = sub;
  drawerBody().innerHTML = body;
  const foot = drawerFoot();
  foot.innerHTML = footer;
  foot.hidden = !footer;
  foot.onclick = (event) => {
    const button = event.target.closest("[data-drawer-action]");
    if (button && typeof onAction === "function") onAction(button.dataset.drawerAction, button);
  };
  drawer().classList.add("open");
  drawer().inert = false;
  drawer().setAttribute("aria-hidden", "false");
  scrim().classList.add("show");
  document.getElementById("wsDrawerClose").focus();
}

export function closeDrawer() {
  drawer().classList.remove("open");
  drawer().inert = true;
  drawer().setAttribute("aria-hidden", "true");
  if (!document.getElementById("wsModalWrap").classList.contains("show")) {
    scrim().classList.remove("show");
  }
}

export function openModal(html, label = "Dialog") {
  const wrap = document.getElementById("wsModalWrap");
  const modal = document.getElementById("wsModal");
  modal.innerHTML = html;
  modal.setAttribute("aria-label", label || "Dialog");
  wrap.classList.add("show");
  scrim().classList.add("show");
  return modal;
}

export function confirmAction(title, text, onConfirm) {
  const modal = openModal(
    `<div class="ws-modal-content">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(text)}</p>
      <div class="ws-modal-actions">
        <button class="ws-btn" type="button" data-modal-action="cancel">取消</button>
        <button class="ws-btn ws-btn-primary" type="button" data-modal-action="confirm">确认</button>
      </div>
    </div>`,
    title,
  );
  modal.onclick = (event) => {
    const button = event.target.closest("[data-modal-action]");
    if (!button) return;
    closeModal();
    if (button.dataset.modalAction === "confirm" && typeof onConfirm === "function") onConfirm();
  };
}

export function closeModal() {
  const wrap = document.getElementById("wsModalWrap");
  wrap.classList.remove("show");
  const modal = document.getElementById("wsModal");
  modal.innerHTML = "";
  modal.onclick = null;
  if (!drawer().classList.contains("open")) scrim().classList.remove("show");
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

export function formatNumber(value) {
  return new Intl.NumberFormat(undefined).format(Number(value) || 0);
}

export function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function bindShell() {
  document.getElementById("wsDrawerClose")?.addEventListener("click", closeDrawer);
  scrim()?.addEventListener("click", () => {
    closeModal();
    closeDrawer();
  });
  document.getElementById("wsModalWrap")?.addEventListener("click", (event) => {
    if (event.target.id === "wsModalWrap") closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (document.getElementById("wsCommand")?.hidden === false) {
      document.getElementById("wsCommand").hidden = true;
      return;
    }
    if (document.getElementById("wsModalWrap").classList.contains("show")) {
      closeModal();
      return;
    }
    if (drawer().classList.contains("open")) closeDrawer();
  });
}
