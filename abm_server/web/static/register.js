import { accountError, initAccountPage, t } from "./account-i18n.js";
import { request, showNotice } from "./api.js";

initAccountPage({ titleKey: "register.pageTitle" });

const form = document.getElementById("register-form");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  const data = Object.fromEntries(new FormData(form));
  button.disabled = true;
  button.textContent = t("register.submitting");
  try {
    await request("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: data.email,
        password: data.password,
        display_name: data.display_name,
        application_note: data.application_note || null,
      }),
    });
    form.reset();
    showNotice(t("register.success"));
  } catch (error) {
    showNotice(accountError(error), true);
  } finally {
    button.disabled = false;
    button.textContent = t("register.submit");
  }
});
