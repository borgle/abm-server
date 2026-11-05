const htmlEscapes = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => htmlEscapes[character]);
}

function detectClientLanguage() {
  const candidates = [];
  try {
    if (Array.isArray(navigator.languages)) candidates.push(...navigator.languages);
    if (navigator.language) candidates.push(navigator.language);
  } catch {
    return "en";
  }
  for (const candidate of candidates) {
    const language = String(candidate || "").toLowerCase();
    if (language.startsWith("zh")) return "zh";
    if (language.startsWith("en")) return "en";
  }
  return "en";
}

export function initPageLanguage({
  translations,
  storageKey = "abm.lang",
  legacyStorageKeys = [],
  defaultLanguage = "auto",
  onApply,
}) {
  let language = translations[defaultLanguage] ? defaultLanguage : "en";
  let copy = translations[language] || translations.en;

  function translate(key, values) {
    let value = copy[key];
    if (typeof value !== "string") return key;
    if (values) {
      for (const [name, replacement] of Object.entries(values)) {
        value = value.replaceAll(`{${name}}`, String(replacement));
      }
    }
    return value;
  }

  function readSavedLanguage() {
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved) return saved;
      for (const legacyKey of legacyStorageKeys) {
        const legacy = window.localStorage.getItem(legacyKey);
        if (legacy) return legacy;
      }
      return null;
    } catch {
      return null;
    }
  }

  function saveLanguage(nextLanguage) {
    try {
      window.localStorage.setItem(storageKey, nextLanguage);
    } catch {
      // Storage can be unavailable in private browsing; the page still switches.
    }
  }

  function applyLanguage(nextLanguage, { persist = true } = {}) {
    const normalized = nextLanguage === "zh" ? "zh" : "en";
    copy = translations[normalized] || translations.en;
    language = normalized;
    const issuerUrl =
      document.querySelector("[data-issuer-url]")?.dataset.issuerUrl || "";
    const releaseUrl =
      document.querySelector("[data-release-url]")?.dataset.releaseUrl || "";

    document.documentElement.lang = normalized === "zh" ? "zh-CN" : "en";
    document.documentElement.dataset.abmLang = normalized;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const value = copy[element.dataset.i18n];
      if (typeof value === "string") {
        element.textContent = value;
      }
    });
    document.querySelectorAll("[data-i18n-html]").forEach((element) => {
      const value = copy[element.dataset.i18nHtml];
      if (typeof value === "string") {
        element.innerHTML = value
          .replaceAll("{issuer}", escapeHtml(issuerUrl))
          .replaceAll("{releaseUrl}", escapeHtml(releaseUrl));
      }
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      const value = copy[element.dataset.i18nPlaceholder];
      if (typeof value === "string") {
        element.placeholder = value;
      }
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => {
      const value = copy[element.dataset.i18nAriaLabel];
      if (typeof value === "string") {
        element.setAttribute("aria-label", value);
      }
    });
    document.querySelectorAll("[data-lang]").forEach((button) => {
      const active = button.dataset.lang === normalized;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    document.title = copy["page.title"] || document.title;
    // 翻译完成后解除首屏隐藏；手动切换时也保持移除。
    document.documentElement.classList.remove("abm-lang-booting");
    if (persist) saveLanguage(normalized);
    if (typeof onApply === "function") onApply(normalized);
  }

  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.addEventListener("click", () => applyLanguage(button.dataset.lang));
  });

  const saved = readSavedLanguage();
  const fallbackLanguage =
    defaultLanguage === "zh" || defaultLanguage === "en"
      ? defaultLanguage
      : detectClientLanguage();
  const initialLanguage =
    saved === "zh" || saved === "en" ? saved : fallbackLanguage;
  applyLanguage(initialLanguage, { persist: false });

  return {
    get language() {
      return language;
    },
    t: translate,
  };
}
