"""Helpers used by several test files."""

from fastapi.testclient import TestClient

STRONG_PASSWORD = "Qwerty1!"


def register(client: TestClient, email: str = "artist@example.com", password: str = STRONG_PASSWORD, **extra) -> dict:
    body = {
        "email": email,
        "password": password,
        "display_name": "Ivan Artist",
        "pd_consent": True,
        "pep_agreement": True,
        **extra,
    }
    response = client.post("/v1/auth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


VALID_BILLING = {
    "payer_type": "individual",
    "last_name": "Иванов",
    "first_name": "Иван",
    "middle_name": "Иванович",
    "email": "ivanov@example.com",
    "phone": "+79001234567",
}


PRODUCER_ACCOUNT = {
    "tax_status": "self_employed",
    "yookassa_account_id": "mock-seller-42",
    "pep_agreement": True,
    "license_terms": True,
}


def make_producer(client: TestClient, email: str = "producer@example.com") -> dict:
    """Registers a user, fills billing details, connects to sales (FR-33) and returns tokens with the role."""
    tokens = register(client, email=email)
    assert client.put("/v1/users/me/billing", json=VALID_BILLING, headers=auth(tokens)).status_code == 200
    response = client.post("/v1/users/me/producer-account", json=PRODUCER_ACCOUNT, headers=auth(tokens))
    assert response.status_code == 201, response.text
    refreshed = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    return refreshed.json()


def beat_body(**overrides) -> dict:
    """A valid POST /beats body (the example of REST API §2.1) with stems and four licenses."""
    body = {
        "title": "Neon Nights",
        "genres": ["Synthwave"],
        "bpm": 120,
        "musical_key": "Dm",
        "description": None,
        "licenses": [
            {"code": "basic", "price": 1500},
            {"code": "premium", "price": 3000},
            {"code": "trackout", "price": 6000},
            {"code": "exclusive", "price": 25000},
        ],
        "files": {
            "wav": {"name": "neon_master.wav", "size_bytes": 61234567, "content_type": "audio/wav"},
            "cover": {"name": "cover.jpg", "size_bytes": 845000, "content_type": "image/jpeg"},
            "stems": {"name": "stems.zip", "size_bytes": 300000000, "content_type": "application/zip"},
        },
    }
    body.update(overrides)
    return body
