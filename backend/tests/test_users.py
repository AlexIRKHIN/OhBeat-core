"""Profile, avatar, billing details, connecting to sales: FR-32, FR-33, NFR-22, REST API §2.9."""

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy import text

from app.common.validators import is_valid_inn
from tests.helpers import VALID_BILLING, auth, register

PRODUCER_BODY = {
    "tax_status": "self_employed",
    "yookassa_account_id": "mock-seller-42",
    "pep_agreement": True,
    "license_terms": True,
}


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_avatar(client, tokens, data: bytes, name="avatar.png", content_type="image/png") -> str:
    form = client.post(
        "/v1/users/me/avatar",
        json={"name": name, "size_bytes": len(data), "content_type": content_type},
        headers=auth(tokens),
    )
    assert form.status_code == 200, form.text
    form = form.json()
    # What the browser does: multipart POST straight to S3, bypassing Core API
    response = httpx.post(form["url"], data=form["fields"], files={"file": (name, data, content_type)})
    assert response.status_code == 204, response.text
    return form["key"]


# --- FR-32: profile and avatar ---

def test_fr32_update_profile(client):
    tokens = register(client)
    response = client.put("/v1/users/me", json={"display_name": "  New Name  ", "bio": "About me"}, headers=auth(tokens))
    assert response.status_code == 200
    assert response.json()["display_name"] == "New Name"
    assert response.json()["bio"] == "About me"


def test_nfr22_avatar_uploaded_checked_and_published(client):
    tokens = register(client)
    key = _upload_avatar(client, tokens, _png(256, 256))
    response = client.put("/v1/users/me", json={"display_name": "Ivan", "avatar_key": key}, headers=auth(tokens))
    assert response.status_code == 200, response.text
    avatar_url = response.json()["avatar_url"]
    assert "/test-public-media/avatars/" in avatar_url
    # The public bucket is readable without a signature
    assert httpx.get(avatar_url).status_code == 200


def test_nfr22_fake_image_rejected_by_content(client):
    tokens = register(client)
    key = _upload_avatar(client, tokens, b"this is not an image at all")
    response = client.put("/v1/users/me", json={"display_name": "Ivan", "avatar_key": key}, headers=auth(tokens))
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "avatar_key"


def test_nfr22_avatar_larger_than_2048_rejected(client):
    tokens = register(client)
    key = _upload_avatar(client, tokens, _png(2049, 10))
    response = client.put("/v1/users/me", json={"display_name": "Ivan", "avatar_key": key}, headers=auth(tokens))
    assert response.status_code == 400


def test_nfr22_avatar_form_rejects_wrong_type_and_size(client):
    tokens = register(client)
    wrong_type = client.post(
        "/v1/users/me/avatar", json={"name": "a.gif", "size_bytes": 10, "content_type": "image/gif"}, headers=auth(tokens)
    )
    too_big = client.post(
        "/v1/users/me/avatar",
        json={"name": "a.png", "size_bytes": 5 * 1024 * 1024 + 1, "content_type": "image/png"},
        headers=auth(tokens),
    )
    assert wrong_type.status_code == too_big.status_code == 400


def test_s3_rejects_file_bigger_than_declared_limit(client):
    """content-length-range in the presigned POST policy: S3 itself refuses a bigger file."""
    tokens = register(client)
    form = client.post(
        "/v1/users/me/avatar", json={"name": "a.png", "size_bytes": 100, "content_type": "image/png"}, headers=auth(tokens)
    ).json()
    oversized = b"0" * (5 * 1024 * 1024 + 10)
    response = httpx.post(form["url"], data=form["fields"], files={"file": ("a.png", oversized, "image/png")})
    assert response.status_code == 400
    assert "EntityTooLarge" in response.text


def test_avatar_key_of_another_user_rejected(client):
    first = register(client, email="first@example.com")
    second = register(client, email="second@example.com")
    key = _upload_avatar(client, first, _png(64, 64))
    response = client.put("/v1/users/me", json={"display_name": "Thief", "avatar_key": key}, headers=auth(second))
    assert response.status_code == 400


# --- FR-32: billing details ---

def test_fr32_billing_not_found_before_first_save(client):
    tokens = register(client)
    assert client.get("/v1/users/me/billing", headers=auth(tokens)).status_code == 404


def test_fr32_billing_individual_saved(client):
    tokens = register(client)
    response = client.put("/v1/users/me/billing", json=VALID_BILLING, headers=auth(tokens))
    assert response.status_code == 200, response.text
    assert client.get("/v1/users/me/billing", headers=auth(tokens)).json()["phone"] == "+79001234567"


def test_fr32_billing_business_requires_company_fields(client):
    tokens = register(client)
    response = client.put("/v1/users/me/billing", json={**VALID_BILLING, "payer_type": "business"}, headers=auth(tokens))
    assert response.status_code == 400
    assert {d["field"] for d in response.json()["details"]} == {"company_name", "inn", "legal_address"}


def test_fr32_billing_business_saved(client):
    tokens = register(client)
    body = {
        **VALID_BILLING,
        "payer_type": "business",
        "company_name": "ООО «Звук»",
        "inn": "7707083893",
        "legal_address": "г. Москва, ул. Примерная, д. 1",
    }
    response = client.put("/v1/users/me/billing", json=body, headers=auth(tokens))
    assert response.status_code == 200, response.text
    assert response.json()["inn"] == "7707083893"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inn", "7707083894"),        # wrong checksum
        ("inn", "12345"),             # wrong length
        ("phone", "89001234567"),     # not E.164
        ("last_name", "Иванов2"),      # digits in a name
        ("email", "not-an-email"),
    ],
)
def test_fr32_billing_invalid_fields(client, field, value):
    tokens = register(client)
    body = {
        **VALID_BILLING,
        "payer_type": "business",
        "company_name": "ООО «Звук»",
        "inn": "7707083893",
        "legal_address": "Москва",
        field: value,
    }
    response = client.put("/v1/users/me/billing", json=body, headers=auth(tokens))
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == field


@pytest.mark.parametrize(
    ("inn", "valid"),
    [
        ("7707083893", True),     # 10 digits, company
        ("500100732259", True),   # 12 digits, sole proprietor
        ("0100000005", False),
        ("500100732258", False),
    ],
)
def test_inn_checksum(inn, valid):
    assert is_valid_inn(inn) is valid


# --- FR-33: connecting to sales ---

def test_fr33_producer_requires_billing(client):
    tokens = register(client)
    response = client.post("/v1/users/me/producer-account", json=PRODUCER_BODY, headers=auth(tokens))
    assert response.status_code == 409
    assert response.json()["error_code"] == "BILLING_REQUIRED"


def test_fr33_connect_producer(client, owner_engine):
    tokens = register(client)
    client.put("/v1/users/me/billing", json=VALID_BILLING, headers=auth(tokens))
    response = client.post("/v1/users/me/producer-account", json=PRODUCER_BODY, headers=auth(tokens))
    assert response.status_code == 201, response.text
    assert response.json()["roles"] == ["artist", "producer"]

    # The new role reaches the access token after refresh
    refreshed = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
    assert client.get("/v1/users/me", headers=auth(refreshed)).json()["roles"] == ["artist", "producer"]

    with owner_engine.connect() as conn:
        audit = conn.execute(text("SELECT details FROM audit_log WHERE action = 'producer.connected'")).scalar_one()
    assert audit["pep_agreement_accepted"] is True


def test_fr33_connect_producer_twice(client):
    tokens = register(client)
    client.put("/v1/users/me/billing", json=VALID_BILLING, headers=auth(tokens))
    client.post("/v1/users/me/producer-account", json=PRODUCER_BODY, headers=auth(tokens))
    again = client.post("/v1/users/me/producer-account", json=PRODUCER_BODY, headers=auth(tokens))
    assert again.status_code == 409
    assert again.json()["error_code"] == "ALREADY_PRODUCER"


@pytest.mark.parametrize("field", ["pep_agreement", "license_terms"])
def test_fr33_agreements_required(client, field):
    tokens = register(client)
    client.put("/v1/users/me/billing", json=VALID_BILLING, headers=auth(tokens))
    response = client.post("/v1/users/me/producer-account", json={**PRODUCER_BODY, field: False}, headers=auth(tokens))
    assert response.status_code == 400


def test_fr33_yookassa_account_id_required(client):
    tokens = register(client)
    client.put("/v1/users/me/billing", json=VALID_BILLING, headers=auth(tokens))
    response = client.post(
        "/v1/users/me/producer-account", json={**PRODUCER_BODY, "yookassa_account_id": "  "}, headers=auth(tokens)
    )
    assert response.status_code == 400


# --- Dictionaries ---

def test_dictionaries_public(client):
    response = client.get("/v1/dictionaries")
    assert response.status_code == 200
    body = response.json()
    assert [lic["code"] for lic in body["licenses"]] == ["basic", "premium", "trackout", "exclusive"]
    assert len(body["musical_keys"]) == 24
    assert body["genres"]
