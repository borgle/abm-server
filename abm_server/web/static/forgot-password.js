import { request, showNotice } from "./api.js";
import { accountError, initAccountPage, t } from "./account-i18n.js";

const form = document.getElementById("forgot-form");
const sent = document.querySelector('[data-i18n="forgot.sent"]');

initAccountPage({ titleKey: "forgot.pageTitle" });

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  const data = Object.fromEntries(new FormData(form));
  button.disabled = true;
  try {
    await request("/api/v1/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email: data.email }),
    });
    form.hidden = true;
    if (sent) sent.hidden = false;
    showNotice(t("forgot.sent"));
  } catch (error) {
    showNotice(accountError(error), true);
    button.disabled = false;
  }
});
