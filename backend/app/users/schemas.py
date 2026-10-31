"""Bodies of /users/me (REST API §2.9)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints, model_validator

from app.auth.schemas import DisplayName
from app.common.validators import check_inn, check_person_name, check_phone, check_true

ImageContentType = Literal["image/jpeg", "image/png", "image/webp"]


# --- Profile ---

class ProfileOut(BaseModel):
    id: int
    email: str
    display_name: str
    bio: str | None
    avatar_url: str | None
    roles: list[str]


class ProfileUpdate(BaseModel):
    display_name: DisplayName
    # ASSUMPTION: GAP-46 — bio is limited to 1000 characters like a beat description
    bio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    # Key returned by POST /users/me/avatar. Omitted: the avatar stays; null: the avatar is removed.
    avatar_key: str | None = Field(default=None, max_length=255)


class AvatarUploadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: ImageContentType


class UploadForm(BaseModel):
    """Presigned POST form: the browser sends `fields` plus the file to `url`."""

    url: str
    fields: dict[str, str]
    key: str
    expires_at: datetime


# --- Billing details (UI spec §2) ---

PersonName = Annotated[str, StringConstraints(max_length=100), AfterValidator(check_person_name)]


class BillingIn(BaseModel):
    payer_type: Literal["individual", "business"]
    last_name: PersonName
    first_name: PersonName
    middle_name: PersonName | None = None
    email: EmailStr = Field(max_length=255)
    phone: Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(check_phone)] | None = None
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    inn: Annotated[str, AfterValidator(check_inn)] | None = None
    legal_address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None

    @model_validator(mode="after")
    def drop_business_fields_for_individual(self) -> "BillingIn":
        # The required-for-business check lives in the service: it reports each missing field separately
        if self.payer_type == "individual":
            self.company_name = self.inn = self.legal_address = None
        return self

    def missing_business_fields(self) -> list[str]:
        """Same rule as CHECK billing_profiles_business_check in schema.sql."""
        if self.payer_type != "business":
            return []
        return [f for f in ("company_name", "inn", "legal_address") if not getattr(self, f)]


class BillingOut(BaseModel):
    payer_type: str
    last_name: str
    first_name: str
    middle_name: str | None
    email: str
    phone: str | None
    company_name: str | None
    inn: str | None
    legal_address: str | None
    updated_at: datetime


# --- Connecting to sales (FR-33) ---

class ProducerAccountIn(BaseModel):
    tax_status: Literal["individual", "self_employed", "ip"]
    yookassa_account_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    pep_agreement: Annotated[bool, AfterValidator(check_true)]
    # ASSUMPTION: GAP-47 — the REST contract names the consent but not the field
    license_terms: Annotated[bool, AfterValidator(check_true)]


class ProducerAccountOut(BaseModel):
    tax_status: str
    yookassa_account_id: str
    pep_agreement_at: datetime
    roles: list[str]
