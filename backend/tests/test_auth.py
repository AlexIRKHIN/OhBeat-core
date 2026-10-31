"""Registration, sign-in and tokens: FR-31, NFR-4, NFR-5, REST API §2.8."""

import pytest
from sqlalchemy import text

from tests.helpers import STRONG_PASSWORD, auth, register

REGISTER_BODY = {
    "email": "artist@example.com",
    "password": STRONG_PASSWORD,
    "display_name": "Ivan Artist",
    "pd_consent": True,
    "pep_agreement": True,
}


# --- FR-31: registration ---

def test_fr31_register_gives_artist_role_and_token_pair(client):
    tokens = register(client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 3600
    me = client.get("/v1/users/me", headers=auth(tokens)).json()
    assert me["roles"] == ["artist"]
    assert me["display_name"] == "Ivan Artist"


def test_fr31_pep_agreement_and_registration_written_to_audit_log(client, owner_engine):
    register(client)
    with owner_engine.connect() as conn:
        actions = set(conn.scalars(text("SELECT action FROM audit_log")))
    assert {"user.registered", "pep_agreement.accepted"} <= actions


@pytest.mark.parametrize("consent", ["pd_consent", "pep_agreement"])
def test_fr31_register_requires_both_consents(client, consent):
    response = client.post("/v1/auth/register", json={**REGISTER_BODY, consent: False})
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["details"][0]["field"] == consent


@pytest.mark.parametrize(
    "password",
    [
        "Qwer1!",        # shorter than 8
        "qwerty12!",     # no uppercase Latin letter
        "Qwertyui!",     # no digit
        "Qwerty123",     # no special character
        "Йцукенг1!",     # uppercase only in Cyrillic
    ],
)
def test_nfr5_weak_passwords_rejected(client, password):
    response = client.post("/v1/auth/register", json={**REGISTER_BODY, "password": password})
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "password"


def test_nfr4_password_stored_as_argon2_hash(client, owner_engine):
    register(client)
    with owner_engine.connect() as conn:
        stored = conn.scalar(text("SELECT password_hash FROM users"))
    assert stored.startswith("$argon2id$")
    assert STRONG_PASSWORD not in stored


def test_fr31_email_taken_case_insensitive(client):
    register(client, email="artist@example.com")
    response = client.post("/v1/auth/register", json={**REGISTER_BODY, "email": "Artist@Example.com"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "EMAIL_TAKEN"


def test_error_message_language_follows_accept_language(client):
    body = {**REGISTER_BODY, "pd_consent": False}
    ru = client.post("/v1/auth/register", json=body).json()
    en = client.post("/v1/auth/register", json=body, headers={"Accept-Language": "en-US"}).json()
    assert ru["message"] == "Некорректные данные запроса"
    assert en["message"] == "Invalid request data"


# --- Sign-in and the attempt limit ---

def test_login_success(client):
    register(client)
    response = client.post("/v1/auth/login", json={"email": "ARTIST@example.com", "password": STRONG_PASSWORD})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_same_error_for_unknown_email_and_wrong_password(client):
    register(client)
    wrong_password = client.post("/v1/auth/login", json={"email": "artist@example.com", "password": "Wrong1!x"})
    unknown_email = client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "Wrong1!x"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["error_code"] == "INVALID_CREDENTIALS"


def test_login_blocked_after_5_failures_even_with_right_password(client):
    register(client)
    for _ in range(5):
        assert client.post("/v1/auth/login", json={"email": "artist@example.com", "password": "Wrong1!x"}).status_code == 401
    blocked = client.post("/v1/auth/login", json={"email": "artist@example.com", "password": STRONG_PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error_code"] == "TOO_MANY_ATTEMPTS"


def test_login_failures_older_than_15_minutes_do_not_count(client, owner_engine):
    register(client)
    for _ in range(5):
        client.post("/v1/auth/login", json={"email": "artist@example.com", "password": "Wrong1!x"})
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE login_attempts SET attempted_at = attempted_at - interval '16 minutes'"))
    response = client.post("/v1/auth/login", json={"email": "artist@example.com", "password": STRONG_PASSWORD})
    assert response.status_code == 200


def test_successful_login_resets_failure_counter(client):
    register(client)
    for _ in range(4):
        client.post("/v1/auth/login", json={"email": "artist@example.com", "password": "Wrong1!x"})
    assert client.post("/v1/auth/login", json={"email": "artist@example.com", "password": STRONG_PASSWORD}).status_code == 200
    for _ in range(4):
        client.post("/v1/auth/login", json={"email": "artist@example.com", "password": "Wrong1!x"})
    assert client.post("/v1/auth/login", json={"email": "artist@example.com", "password": STRONG_PASSWORD}).status_code == 200


# --- Refresh token rotation and logout ---

def test_refresh_rotates_token(client, owner_engine):
    tokens = register(client)
    response = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # The used token is revoked at once
    again = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert again.status_code == 401
    # Only hashes are stored, never the tokens themselves
    with owner_engine.connect() as conn:
        hashes = list(conn.scalars(text("SELECT token_hash FROM refresh_tokens")))
    assert tokens["refresh_token"] not in hashes


def test_reuse_of_revoked_refresh_token_revokes_whole_family(client):
    tokens = register(client)
    second = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
    # Someone presents the old (already used) token: possible theft
    assert client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    # The legitimate newest token is revoked too
    assert client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client):
    tokens = register(client)
    response = client.post("/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=auth(tokens))
    assert response.status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_protected_endpoint_requires_token(client):
    response = client.get("/v1/users/me")
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_ERROR"
    bad = client.get("/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
