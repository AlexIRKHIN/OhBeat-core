"""Request and response bodies of /auth (REST API §2.8)."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

from app.common.validators import check_password, check_true

Password = Annotated[str, Field(max_length=128), AfterValidator(check_password)]
# ASSUMPTION: GAP-46 — the length of display_name is limited only by profiles.display_name varchar(100)
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: Password
    display_name: DisplayName
    pd_consent: Annotated[bool, AfterValidator(check_true)]  # NFR-30
    pep_agreement: Annotated[bool, AfterValidator(check_true)]  # RFC ПЭП §1


class LoginRequest(BaseModel):
    # Not EmailStr on purpose: a malformed email gets the same 401 as a wrong password
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=255)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
