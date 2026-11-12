"""Bodies of the signature endpoints (RFC ПЭП §4, REST API §2.12)."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, StringConstraints

from app.common.validators import fail


def _six_digits(value: str) -> str:
    if len(value) != 6 or not value.isdigit():
        raise fail("code_format")
    return value


class DraftItemOut(BaseModel):
    item_id: int
    contract_number: str
    title: str
    license: str
    text: str
    draft_sha256: str


class Drafts(BaseModel):
    """ASSUMPTION: GAP-73 — one entry per Exclusive item of the order."""

    items: list[DraftItemOut]


class CodeSent(BaseModel):
    expires_at: datetime
    resend_after: datetime
    phone: str  # masked: +7 (900) ***-**-67 — where the code went


class VerifyIn(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_six_digits)]


class Signed(BaseModel):
    signed_at: datetime
