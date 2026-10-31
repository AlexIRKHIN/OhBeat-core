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
