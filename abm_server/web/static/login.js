import { accountError, initAccountPage, t } from "./account-i18n.js";
import { request, showNotice } from "./api.js";

initAccountPage({ titleKey: "login.pageTitle" });

const form = document.getElementById("login-form");
const params = new URLSearchParams(window.location.search);

function socialErrorMessage(code) {
  const key = `social.error.${code}`;
  const message = t(key);
  return message === key ? t("social.error.unknown") : message;
}

const socialError = params.get("social_error");
if (socialError) {
  showNotice(socialErrorMessage(socialError), true);
}
if (params.get("social") === "linked") {
  showNotice(t("social.linked"));
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  const data = Object.fromEntries(new FormData(form));
  button.disabled = true;
  button.textContent = t("login.submitting");
  try {
    const result = await request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
    const next = params.get("next");
    const target =
      next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\")
        ? next
        : result.user.role === "admin"
          ? "/admin"
          : "/console";
    window.location.assign(target);
  } catch (error) {
    showNotice(
      accountError(error, { ABM_INVALID_CREDENTIALS: "login.invalid" }),
      true,
    );
  } finally {
    button.disabled = false;
    button.textContent = t("login.submit");
  }
});
