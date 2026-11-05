import { accountError, initAccountPage, t } from "./account-i18n.js";
import { request, showNotice } from "./api.js";

const params = new URLSearchParams(window.location.search);
const token = params.get("token") || "";
const form = document.getElementById("social-complete-form");
const meta = document.getElementById("social-complete-meta");
const mark = document.getElementById("social-complete-mark");
const providerElement = document.getElementById("social-complete-provider");
const status = document.getElementById("social-complete-status");
const emailInput = form.querySelector('input[name="email"]');
const nameInput = form.querySelector('input[name="display_name"]');
const submitButton = form.querySelector('button[type="submit"]');

let pending = null;
let terminal = false;

function providerMark(providerId) {
  mark.className = `social-mark social-mark-${providerId}`;
  mark.replaceChildren();
  if (providerId === "wechat") {
    mark.textContent = "微";
  } else if (providerId === "qq") {
    mark.textContent = "QQ";
  } else if (providerId === "google") {
    mark.textContent = "G";
  } else if (providerId === "github") {
    mark.textContent = "GH";
  } else if (providerId === "microsoft") {
    for (let index = 0; index < 4; index += 1) {
      mark.appendChild(document.createElement("span"));
    }
  } else {
    mark.textContent = (providerId || "?").slice(0, 1).toUpperCase();
  }
}

function providerDisplayName(provider) {
  const key = `provider.${provider.id}`;
  const label = t(key);
  return label === key ? provider.name || provider.id : label;
}

function renderPending() {
  if (!pending) return;
  meta.hidden = false;
  providerMark(pending.provider);
  providerElement.textContent = t("socialComplete.provider", {
    provider: providerDisplayName({
      id: pending.provider,
      name: pending.providerName,
    }),
  });
  if (!terminal) {
    form.hidden = false;
  }
}

function showFailure(error) {
  terminal = true;
  meta.hidden = true;
  form.hidden = true;
  status.hidden = false;
  status.textContent = accountError(error, {
    ABM_SOCIAL_PENDING_INVALID: "socialComplete.invalid",
  });
  showNotice(status.textContent, true);
}

initAccountPage({
  titleKey: "socialComplete.pageTitle",
  onChange() {
    renderPending();
  },
});

async function loadPending() {
  if (!token) {
    showFailure({ code: "ABM_SOCIAL_PENDING_INVALID" });
    return;
  }
  try {
    pending = await request(
      `/api/v1/auth/social/pending/${encodeURIComponent(token)}`,
    );
    nameInput.value = pending.displayName || "";
    renderPending();
  } catch (error) {
    showFailure(error);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!pending || terminal) return;
  submitButton.disabled = true;
  submitButton.textContent = t("socialComplete.submitting");
  try {
    const result = await request("/api/v1/auth/social/complete", {
      method: "POST",
      body: JSON.stringify({
        token,
        email: emailInput.value,
        display_name: nameInput.value,
      }),
    });
    if (result.status === "pending") {
      terminal = true;
      form.hidden = true;
      status.hidden = false;
      status.textContent = t("socialComplete.pending");
      showNotice(t("socialComplete.pending"));
      return;
    }
    showNotice(t("socialComplete.success"));
    window.location.assign(result.next || "/console");
  } catch (error) {
    showNotice(
      accountError(error, {
        ABM_SOCIAL_EMAIL_CONFLICT: "socialComplete.conflict",
        ABM_SOCIAL_PENDING_INVALID: "socialComplete.invalid",
      }),
      true,
    );
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = t("socialComplete.submit");
  }
});

loadPending();
