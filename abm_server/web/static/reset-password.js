import { request, showNotice } from "./api.js";
import { accountError, initAccountPage, t } from "./account-i18n.js";

const form = document.getElementById("reset-form");
const success = document.querySelector('[data-i18n="reset.success"]');
const invalid = document.querySelector('[data-i18n="reset.invalid"]');
const token = new URLSearchParams(window.location.search).get("token") || "";

initAccountPage({ titleKey: "reset.pageTitle" });

if (!token) {
  form.hidden = true;
  if (invalid) invalid.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  const data = Object.fromEntries(new FormData(form));
  if (data.password !== data.confirm) {
    showNotice(t("reset.mismatch"), true);
    return;
  }
  button.disabled = true;
  try {
    await request("/api/v1/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify({ token, new_password: data.password }),
    });
    form.hidden = true;
    if (success) success.hidden = false;
    showNotice(t("reset.success"));
  } catch (error) {
    if (error?.code === "ABM_TOKEN_INVALID") {
      form.hidden = true;
      if (invalid) invalid.hidden = false;
    }
    showNotice(accountError(error), true);
    button.disabled = false;
  }
});
