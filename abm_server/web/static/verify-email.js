import { request, showNotice } from "./api.js";
import { accountError, initAccountPage, t } from "./account-i18n.js";

const status = document.getElementById("verify-status");
const token = new URLSearchParams(window.location.search).get("token") || "";

initAccountPage({ titleKey: "verify.pageTitle" });

async function verify() {
  if (!token) {
    status.textContent = t("verify.invalid");
    return;
  }
  try {
    await request("/api/v1/auth/email-verification/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    status.textContent = t("verify.success");
    showNotice(t("verify.success"));
  } catch (error) {
    status.textContent = t("verify.invalid");
    showNotice(accountError(error), true);
  }
}

void verify();
