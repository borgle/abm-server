from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel

from .models import PlanCode, UserStatus


class CamelResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    application_note: str | None = Field(default=None, max_length=2000)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name must not be blank")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class AccountDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class EmailRequest(BaseModel):
    email: EmailStr


class TokenConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=256)


class SocialCompleteRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_social_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name must not be blank")
        return value


class UserResponse(CamelResponse):
    id: str
    email: str
    display_name: str
    role: str
    status: str
    plan_code: str
    plan_expires_at: datetime | None
    email_verified_at: datetime | None
    created_at: datetime


class AuthResponse(CamelResponse):
    user: UserResponse
    csrf_token: str


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ApiKeyResponse(CamelResponse):
    id: str
    name: str
    prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreateResponse(ApiKeyResponse):
    plaintext: str


class AdminUserPatch(BaseModel):
    status: UserStatus | None = None
    plan_code: PlanCode | None = None
    plan_expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=1000)


class AdminUserResponse(UserResponse):
    application_note: str | None
    status_reason: str | None
    approved_at: datetime | None
    approved_by: str | None
    usage: dict[str, int] | None = None


class AdminUserListResponse(CamelResponse):
    items: list[AdminUserResponse]
    total: int = 0


class SystemSettingsResponse(CamelResponse):
    registration_require_approval: bool


class SystemSettingsPatch(BaseModel):
    registration_require_approval: bool


class CreationProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1, max_length=500)


class CreationProviderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class LocalModelPatch(BaseModel):
    provider_id: str | None = None
    model: str | None = Field(default=None, max_length=200)
    fallback_model: str | None = Field(default=None, max_length=200)
    image_provider_id: str | None = None
    image_model: str | None = Field(default=None, max_length=200)
    image_max_n: int | None = Field(default=None, ge=1, le=4)


class CreationPlanPatch(BaseModel):
    provider_id: str | None = None
    model: str | None = Field(default=None, max_length=200)
    fallback_model: str | None = Field(default=None, max_length=200)
    token_quota_month: int | None = Field(default=None, ge=0)
    generations_per_day: int | None = Field(default=None, ge=0)
    pages_per_month: int | None = Field(default=None, ge=0)
    storage_bytes: int | None = Field(default=None, ge=0)
    max_upload_bytes: int | None = Field(default=None, ge=0)
    image_provider_id: str | None = None
    image_model: str | None = Field(default=None, max_length=200)
    image_generations_per_day: int | None = Field(default=None, ge=0)
    image_max_n: int | None = Field(default=None, ge=1, le=4)
    browser_connections: int | None = Field(default=None, ge=1)
    browser_sessions: int | None = Field(default=None, ge=1)
    reserved_priority_slots: int | None = Field(default=None, ge=0)


class CreationSystemPatch(BaseModel):
    enabled: bool | None = None
    byok_enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    trash_days: int | None = Field(default=None, ge=1, le=365)


class AdminSystemPatch(CreationSystemPatch):
    registration_require_approval: bool | None = None


class CreationProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    default_platform: str = Field(default="master", max_length=32)


class CreationProjectPatch(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    default_platform: str | None = Field(default=None, max_length=32)


class CreationAssetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="article", max_length=32)
    project_id: str | None = None
    platform: str = Field(default="master", max_length=32)
    content_md: str = Field(default="", max_length=500_000)


class CreationAssetPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=32)
    platform: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = None


class CreationVersionCreate(BaseModel):
    content_md: str = Field(default="", max_length=500_000)
    title: str | None = Field(default=None, max_length=200)
    outline: list | None = None
    brief: dict | None = None
    citations: list | None = None
    source_ids: list | None = None


class CreationGenerateRequest(BaseModel):
    platform: str = Field(default="master", max_length=32)
    source_ids: list[str] = Field(min_length=1, max_length=24)
    asset_id: str | None = None
    project_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    brief: dict = Field(default_factory=dict)


class CreationMediaGenerateRequest(BaseModel):
    kind: str = Field(default="cover", max_length=16)
    platform: str = Field(default="master", max_length=32)
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = Field(default=None, max_length=32)
    asset_version_id: str | None = None
    reference_media_id: str | None = None


class CreationMediaPatch(BaseModel):
    role: str | None = Field(default=None, max_length=16)
    kind: str | None = Field(default=None, max_length=16)


class CreationExportCreate(BaseModel):
    target: str = Field(max_length=16)
    style_id: str = Field(default="default", max_length=32)
    options: dict = Field(default_factory=dict)


class SystemConfigPatch(BaseModel):
    values: dict


class SystemConfigImport(BaseModel):
    values: dict
    mode: str = Field(default="merge", max_length=16)


class CreationPublicationCreate(BaseModel):
    asset_id: str
    platform: str = Field(max_length=32)


class CreationPublicationPublish(BaseModel):
    url: str | None = Field(default=None, max_length=2000)


class CreationResearchResume(BaseModel):
    skip_engine: str | None = Field(default=None, max_length=32)
    skip_current: bool = False


class CreationResearchJobCreate(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=5)
    exclusions: list[str] = Field(default_factory=list, max_length=10)
    engines: list[str] = Field(default_factory=list, max_length=5)
    depth: str = Field(default="standard", max_length=16)
    language: str = Field(default="zh", max_length=8)
    project_id: str | None = None


class AuditEventResponse(CamelResponse):
    id: str
    actor_user_id: str | None
    actor_name: str | None = None
    subject_user_id: str | None
    subject_name: str | None = None
    api_key_id: str | None
    event_type: str
    metadata: dict
    created_at: datetime


class AuditListResponse(CamelResponse):
    items: list[AuditEventResponse]
    total: int = 0


class AcceptedResponse(BaseModel):
    status: str = "accepted"
