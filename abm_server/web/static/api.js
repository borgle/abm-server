const notice = document.getElementById("notice");
let noticeTimer;

function isEnglish() {
  return document.documentElement.lang.toLowerCase().startsWith("en");
}

export function showNotice(message, isError = false) {
  if (!notice) return;
  clearTimeout(noticeTimer);
  notice.hidden = false;
  notice.textContent = message;
  notice.classList.toggle("error", isError);
  noticeTimer = setTimeout(() => {
    notice.hidden = true;
  }, 4200);
}

export function csrfToken() {
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith("abm_csrf="));
  return item ? decodeURIComponent(item.slice("abm_csrf=".length)) : "";
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", csrfToken());
  }
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fallback = isEnglish()
      ? `Request failed (${response.status})`
      : `请求失败 (${response.status})`;
    const error = new Error(data?.error?.message || fallback);
    error.code = data?.error?.code;
    error.status = response.status;
    error.action = data?.error?.action;
    throw error;
  }
  return data;
}

export async function requireUser() {
  try {
    return await request("/api/v1/auth/me");
  } catch (error) {
    if (error.status === 401) {
      window.location.assign("/login");
      return null;
    }
    throw error;
  }
}

export async function logout() {
  try {
    await request("/api/v1/auth/logout", { method: "POST" });
  } finally {
    window.location.assign("/login");
  }
}

export function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(isEnglish() ? "en-US" : "zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

