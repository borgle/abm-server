"""Social login provider adapters.

Only a small, explicit set of providers is supported. Each adapter turns an
OAuth/OIDC authorization code into a normalized user profile. Provider
credentials stay on the server and are never exposed to the browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx

from ..config import Settings


class SocialProviderError(RuntimeError):
    """Raised when a provider rejects a token or profile request."""

    def __init__(self, message: str, *, provider: str):
        super().__init__(message)
        self.provider = provider


@dataclass(frozen=True, slots=True)
class SocialProvider:
    id: str
    name: str
    authorize_url: str
    token_url: str
    userinfo_url: str | None
    scope: str
    client_id: str
    client_secret: str
    use_pkce: bool = True
    client_id_param: str = "client_id"
    token_client_id_param: str = "client_id"
    token_client_secret_param: str = "client_secret"
    token_request: str = "post"
    token_params: dict[str, str] = field(default_factory=dict)
    authorize_fragment: str = ""
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    requires_email: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(frozen=True, slots=True)
class SocialProfile:
    provider: str
    subject: str
    email: str | None
    email_verified: bool
    display_name: str
    avatar_url: str | None = None


def _google(settings: Settings) -> SocialProvider:
    return SocialProvider(
        id="google",
        name="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
        client_id=settings.social_google_client_id.strip(),
        client_secret=settings.social_google_client_secret.strip(),
        extra_authorize_params={"prompt": "select_account"},
    )


def _github(settings: Settings) -> SocialProvider:
    return SocialProvider(
        id="github",
        name="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
        client_id=settings.social_github_client_id.strip(),
        client_secret=settings.social_github_client_secret.strip(),
    )


def _microsoft(settings: Settings) -> SocialProvider:
    tenant = settings.social_microsoft_tenant.strip() or "common"
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    return SocialProvider(
        id="microsoft",
        name="Microsoft",
        authorize_url=f"{base}/authorize",
        token_url=f"{base}/token",
        userinfo_url="https://graph.microsoft.com/oidc/userinfo",
        scope="openid email profile",
        client_id=settings.social_microsoft_client_id.strip(),
        client_secret=settings.social_microsoft_client_secret.strip(),
        extra_authorize_params={"response_mode": "query"},
    )


def _wechat(settings: Settings) -> SocialProvider:
    return SocialProvider(
        id="wechat",
        name="WeChat",
        authorize_url="https://open.weixin.qq.com/connect/qrconnect",
        token_url="https://api.weixin.qq.com/sns/oauth2/access_token",
        userinfo_url="https://api.weixin.qq.com/sns/userinfo",
        scope="snsapi_login",
        client_id=settings.social_wechat_client_id.strip(),
        client_secret=settings.social_wechat_client_secret.strip(),
        use_pkce=False,
        client_id_param="appid",
        token_client_id_param="appid",
        token_client_secret_param="secret",
        token_request="get",
        authorize_fragment="#wechat_redirect",
        requires_email=True,
    )


def _qq(settings: Settings) -> SocialProvider:
    return SocialProvider(
        id="qq",
        name="QQ",
        authorize_url="https://graph.qq.com/oauth2.0/authorize",
        token_url="https://graph.qq.com/oauth2.0/token",
        userinfo_url="https://graph.qq.com/user/get_user_info",
        scope="get_user_info",
        client_id=settings.social_qq_client_id.strip(),
        client_secret=settings.social_qq_client_secret.strip(),
        use_pkce=False,
        token_request="get",
        token_params={"fmt": "json"},
        requires_email=True,
    )


def _catalog(settings: Settings) -> list[SocialProvider]:
    if not settings.social_login_enabled:
        return []
    return [
        _wechat(settings),
        _qq(settings),
        _google(settings),
        _github(settings),
        _microsoft(settings),
    ]


def enabled_social_providers(settings: Settings) -> list[SocialProvider]:
    return [provider for provider in _catalog(settings) if provider.configured]


def get_social_provider(settings: Settings, provider_id: str) -> SocialProvider | None:
    for provider in enabled_social_providers(settings):
        if provider.id == provider_id:
            return provider
    return None


def public_provider_descriptors(settings: Settings) -> list[dict[str, object]]:
    return [
        {
            "id": provider.id,
            "name": provider.name,
            "requiresEmail": provider.requires_email,
        }
        for provider in enabled_social_providers(settings)
    ]


def build_authorize_url(
    provider: SocialProvider,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    params = {
        provider.client_id_param: provider.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
        **provider.extra_authorize_params,
    }
    if provider.use_pkce:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    url = f"{provider.authorize_url}?{urlencode(params)}"
    if provider.authorize_fragment:
        url = f"{url}{provider.authorize_fragment}"
    return url


async def exchange_code_for_profile(
    provider: SocialProvider,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> SocialProfile:
    """Exchange an authorization code and return a normalized profile."""

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        provider.token_client_id_param: provider.client_id,
        provider.token_client_secret_param: provider.client_secret,
        **provider.token_params,
    }
    if provider.use_pkce:
        data["code_verifier"] = code_verifier

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if provider.token_request == "get":
                token_response = await client.get(
                    provider.token_url,
                    params=data,
                    headers={"Accept": "application/json"},
                )
            else:
                token_response = await client.post(
                    provider.token_url,
                    data=data,
                    headers={"Accept": "application/json"},
                )
            token_response.raise_for_status()
            token = token_response.json()
            if provider.id == "wechat":
                return await _wechat_profile(client, provider, token)
            if provider.id == "qq":
                return await _qq_profile(client, provider, token)
            access_token = token.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise SocialProviderError(
                    "Provider did not return an access token.",
                    provider=provider.id,
                )
            if provider.id == "github":
                return await _github_profile(client, provider, access_token)
            return await _oidc_profile(client, provider, access_token)
    except SocialProviderError:
        raise
    except httpx.HTTPError as exc:
        raise SocialProviderError(
            f"Provider request failed ({type(exc).__name__}).",
            provider=provider.id,
        ) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise SocialProviderError(
            "Provider returned an unexpected profile response.",
            provider=provider.id,
        ) from exc


async def _wechat_profile(
    client: httpx.AsyncClient,
    provider: SocialProvider,
    token: dict,
) -> SocialProfile:
    _raise_wechat_error(token, provider)
    access_token = token.get("access_token")
    openid = token.get("openid")
    if not isinstance(access_token, str) or not access_token:
        raise SocialProviderError("WeChat did not return an access token.", provider=provider.id)
    if not isinstance(openid, str) or not openid:
        raise SocialProviderError("WeChat did not return an openid.", provider=provider.id)

    response = await client.get(
        provider.userinfo_url or "",
        params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    _raise_wechat_error(payload, provider, fallback=token)
    subject = payload.get("unionid") or token.get("unionid") or payload.get("openid") or openid
    nickname = payload.get("nickname") or "WeChat user"
    avatar = payload.get("headimgurl")
    return SocialProfile(
        provider=provider.id,
        subject=str(subject),
        email=None,
        email_verified=False,
        display_name=str(nickname).strip()[:120] or "WeChat user",
        avatar_url=str(avatar) if avatar else None,
    )


def _raise_wechat_error(
    payload: dict,
    provider: SocialProvider,
    *,
    fallback: dict | None = None,
) -> None:
    code = payload.get("errcode")
    if code in (None, 0, "0"):
        return
    source = fallback or payload
    message = source.get("errmsg") or payload.get("errmsg") or f"WeChat error {code}"
    raise SocialProviderError(str(message), provider=provider.id)


async def _qq_profile(
    client: httpx.AsyncClient,
    provider: SocialProvider,
    token: dict,
) -> SocialProfile:
    if token.get("error"):
        raise SocialProviderError(
            str(token.get("error_description") or token["error"]), provider=provider.id
        )
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise SocialProviderError("QQ did not return an access token.", provider=provider.id)

    me_response = await client.get(
        "https://graph.qq.com/oauth2.0/me",
        params={"access_token": access_token, "fmt": "json"},
        headers={"Accept": "application/json"},
    )
    me_response.raise_for_status()
    me = me_response.json()
    if me.get("error"):
        raise SocialProviderError(
            str(me.get("error_description") or me["error"]), provider=provider.id
        )
    openid = me.get("openid")
    if not isinstance(openid, str) or not openid:
        raise SocialProviderError("QQ did not return an openid.", provider=provider.id)

    response = await client.get(
        provider.userinfo_url or "",
        params={
            "access_token": access_token,
            "oauth_consumer_key": provider.client_id,
            "openid": openid,
            "fmt": "json",
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    ret = payload.get("ret")
    if ret not in (None, 0, "0"):
        raise SocialProviderError(
            str(payload.get("msg") or f"QQ error {ret}"),
            provider=provider.id,
        )
    subject = me.get("unionid") or openid
    nickname = payload.get("nickname") or "QQ user"
    avatar = payload.get("figureurl_qq_2") or payload.get("figureurl_qq_1")
    return SocialProfile(
        provider=provider.id,
        subject=str(subject),
        email=None,
        email_verified=False,
        display_name=str(nickname).strip()[:120] or "QQ user",
        avatar_url=str(avatar) if avatar else None,
    )


async def _oidc_profile(
    client: httpx.AsyncClient,
    provider: SocialProvider,
    access_token: str,
) -> SocialProfile:
    if provider.userinfo_url is None:
        raise SocialProviderError("Provider has no userinfo endpoint.", provider=provider.id)
    response = await client.get(
        provider.userinfo_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    response.raise_for_status()
    payload = response.json()
    subject = payload.get("sub")
    email = payload.get("email")
    if not isinstance(subject, str) or not subject:
        raise SocialProviderError("Provider profile has no subject.", provider=provider.id)
    if not isinstance(email, str) or not email.strip():
        raise SocialProviderError("Provider profile has no email.", provider=provider.id)
    verified = payload.get("email_verified")
    if isinstance(verified, str):
        verified = verified.strip().lower() == "true"
    # Microsoft does not emit email_verified in the OIDC userinfo response,
    # but the email claim is only returned for an authenticated account.
    email_verified = bool(verified) if provider.id != "microsoft" else True
    display_name = payload.get("name") or payload.get("given_name") or email.split("@", 1)[0]
    avatar_url = payload.get("picture")
    return SocialProfile(
        provider=provider.id,
        subject=subject,
        email=email.strip().casefold(),
        email_verified=email_verified,
        display_name=str(display_name).strip()[:120] or email.split("@", 1)[0],
        avatar_url=str(avatar_url) if avatar_url else None,
    )


async def _github_profile(
    client: httpx.AsyncClient,
    provider: SocialProvider,
    access_token: str,
) -> SocialProfile:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    profile_response = await client.get(provider.userinfo_url or "", headers=headers)
    profile_response.raise_for_status()
    profile = profile_response.json()
    subject = profile.get("id")
    if subject is None:
        raise SocialProviderError("GitHub profile has no id.", provider=provider.id)

    email = profile.get("email")
    email_verified = False
    emails_response = await client.get(
        "https://api.github.com/user/emails",
        headers=headers,
    )
    emails_response.raise_for_status()
    emails = emails_response.json()
    if isinstance(emails, list):
        primary = next(
            (
                item
                for item in emails
                if isinstance(item, dict)
                and item.get("primary")
                and item.get("verified")
                and item.get("email")
            ),
            None,
        )
        if primary is None:
            primary = next(
                (
                    item
                    for item in emails
                    if isinstance(item, dict) and item.get("verified") and item.get("email")
                ),
                None,
            )
        if primary is not None:
            email = primary.get("email")
            email_verified = True

    if not isinstance(email, str) or not email.strip():
        raise SocialProviderError("GitHub profile has no email.", provider=provider.id)
    display_name = profile.get("name") or profile.get("login") or email.split("@", 1)[0]
    avatar_url = profile.get("avatar_url")
    return SocialProfile(
        provider=provider.id,
        subject=str(subject),
        email=email.strip().casefold(),
        email_verified=email_verified,
        display_name=str(display_name).strip()[:120] or email.split("@", 1)[0],
        avatar_url=str(avatar_url) if avatar_url else None,
    )
