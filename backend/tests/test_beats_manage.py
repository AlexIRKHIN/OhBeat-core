""""My beats", prices and statuses: FR-34, FR-8, NFR-20, REST API §2.4, §2.10."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.catalog.service import delete_abandoned_uploads
from app.common.db import get_session_factory
from tests.helpers import auth, beat_body, make_producer


@pytest.fixture
def producer(client):
    return make_producer(client)


def _create(client, tokens, **overrides) -> int:
    response = client.post("/v1/beats", json=beat_body(**overrides), headers=auth(tokens))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _set_status(owner_engine, beat_id: int, status: str) -> None:
    """Tests jump over states that are reached through Media Worker or payments in later slices."""
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = :s WHERE id = :id"), {"s": status, "id": beat_id})


# --- "My beats" ---

def test_fr34_my_beats_lists_all_but_deleted_with_reason(client, producer, owner_engine):
    first, second, third = (_create(client, producer, title=f"Beat {i}") for i in range(3))
    _set_status(owner_engine, second, "deleted")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'rejected', rejection_reason = 'Битый архив' WHERE id = :id"), {"id": third})

    items = client.get("/v1/users/me/beats", headers=auth(producer)).json()["items"]
    assert [i["id"] for i in items] == [third, first]
    assert items[0]["status"] == "rejected"
    assert items[0]["rejection_reason"] == "Битый архив"
    assert items[1]["licenses"][0] == {"code": "basic", "price": 1500, "is_active": True}


def test_fr34_my_beats_cursor_pagination(client, producer):
    ids = [_create(client, producer, title=f"Beat {i}") for i in range(5)]
    page1 = client.get("/v1/users/me/beats?limit=2", headers=auth(producer)).json()
    page2 = client.get(f"/v1/users/me/beats?limit=2&cursor={page1['next_cursor']}", headers=auth(producer)).json()
    page3 = client.get(f"/v1/users/me/beats?limit=2&cursor={page2['next_cursor']}", headers=auth(producer)).json()
    seen = [i["id"] for p in (page1, page2, page3) for i in p["items"]]
    assert seen == sorted(ids, reverse=True)
    assert page3["next_cursor"] is None


def test_my_beats_shows_only_own(client, producer):
    _create(client, producer)
    other = make_producer(client, email="other@example.com")
    assert client.get("/v1/users/me/beats", headers=auth(other)).json()["items"] == []


# --- Beat page ---

def test_beat_page_owner_sees_any_status_public_only_active(client, producer, owner_engine):
    beat_id = _create(client, producer)
    assert client.get(f"/v1/beats/{beat_id}", headers=auth(producer)).json()["status"] == "uploading"
    assert client.get(f"/v1/beats/{beat_id}").status_code == 404
    _set_status(owner_engine, beat_id, "active")
    public = client.get(f"/v1/beats/{beat_id}").json()
    assert public["status"] is None  # owner-only field
    assert public["is_reserved"] is False


# --- Prices (REST API §2.4) ---

def test_update_price(client, producer):
    beat_id = _create(client, producer)
    response = client.put(f"/v1/beats/{beat_id}/licenses/premium", json={"price": 2000, "is_active": True}, headers=auth(producer))
    assert response.status_code == 200, response.text
    premium = next(lic for lic in response.json()["licenses"] if lic["code"] == "premium")
    assert premium == {"code": "premium", "price": 2000, "is_active": True}


def test_gap52_put_creates_missing_license(client, producer):
    beat_id = _create(client, producer, licenses=[{"code": "basic", "price": 1500}])
    response = client.put(f"/v1/beats/{beat_id}/licenses/premium", json={"price": 3000}, headers=auth(producer))
    assert response.status_code == 200
    assert {lic["code"] for lic in response.json()["licenses"]} == {"basic", "premium"}


def test_last_active_license_cannot_be_disabled(client, producer):
    beat_id = _create(client, producer, licenses=[{"code": "basic", "price": 1500}])
    response = client.put(f"/v1/beats/{beat_id}/licenses/basic", json={"price": 1500, "is_active": False}, headers=auth(producer))
    assert response.status_code == 409
    assert response.json()["error_code"] == "LAST_ACTIVE_LICENSE"


def test_stems_required_to_enable_trackout(client, producer):
    body = beat_body(licenses=[{"code": "basic", "price": 1500}])
    del body["files"]["stems"]
    beat_id = client.post("/v1/beats", json=body, headers=auth(producer)).json()["id"]
    response = client.put(f"/v1/beats/{beat_id}/licenses/trackout", json={"price": 5000}, headers=auth(producer))
    assert response.status_code == 409
    assert response.json()["error_code"] == "STEMS_REQUIRED"


def test_gap54_stems_without_trackout_allow_enabling_it_later(client, producer):
    beat_id = _create(client, producer, licenses=[{"code": "basic", "price": 1500}])  # body still has stems
    response = client.put(f"/v1/beats/{beat_id}/licenses/trackout", json={"price": 5000}, headers=auth(producer))
    assert response.status_code == 200


def test_prices_locked_on_sold_beat(client, producer, owner_engine):
    beat_id = _create(client, producer)
    _set_status(owner_engine, beat_id, "sold")
    response = client.put(f"/v1/beats/{beat_id}/licenses/basic", json={"price": 2000}, headers=auth(producer))
    assert response.status_code == 409
    assert response.json()["error_code"] == "BEAT_SOLD"


def test_price_limits_and_unknown_code(client, producer):
    beat_id = _create(client, producer)
    assert client.put(f"/v1/beats/{beat_id}/licenses/basic", json={"price": 99}, headers=auth(producer)).status_code == 400
    assert client.put(f"/v1/beats/{beat_id}/licenses/gold", json={"price": 100}, headers=auth(producer)).status_code == 404


def test_someone_elses_beat_forbidden(client, producer):
    beat_id = _create(client, producer)
    other = make_producer(client, email="other@example.com")
    assert client.put(f"/v1/beats/{beat_id}/licenses/basic", json={"price": 2000}, headers=auth(other)).status_code == 403
    assert client.patch(f"/v1/beats/{beat_id}", json={"status": "hidden"}, headers=auth(other)).status_code == 403
    assert client.delete(f"/v1/beats/{beat_id}", headers=auth(other)).status_code == 403


# --- Hide, return, delete ---

def test_hide_and_return(client, producer, owner_engine):
    beat_id = _create(client, producer)
    _set_status(owner_engine, beat_id, "active")
    assert client.patch(f"/v1/beats/{beat_id}", json={"status": "hidden"}, headers=auth(producer)).json()["status"] == "hidden"
    assert client.patch(f"/v1/beats/{beat_id}", json={"status": "active"}, headers=auth(producer)).json()["status"] == "active"


@pytest.mark.parametrize(
    ("status", "error_code"),
    [("reserved", "BEAT_RESERVED"), ("sold", "BEAT_SOLD"), ("processing", "INVALID_STATUS"), ("rejected", "INVALID_STATUS")],
)
def test_hide_and_delete_forbidden_states(client, producer, owner_engine, status, error_code):
    beat_id = _create(client, producer)
    if status == "reserved":
        with owner_engine.begin() as conn:
            conn.execute(text("INSERT INTO orders (customer_id, status, total_amount, billing_snapshot) "
                              "SELECT id, 'pending', 100, '{}' FROM users LIMIT 1"))
            conn.execute(text("UPDATE beats SET status = 'reserved', reserved_order_id = (SELECT max(id) FROM orders), "
                              "reserved_until = now() + interval '15 minutes' WHERE id = :id"), {"id": beat_id})
    else:
        _set_status(owner_engine, beat_id, status)
    hide = client.patch(f"/v1/beats/{beat_id}", json={"status": "hidden"}, headers=auth(producer))
    delete = client.delete(f"/v1/beats/{beat_id}", headers=auth(producer))
    assert hide.status_code == delete.status_code == 409
    assert hide.json()["error_code"] == delete.json()["error_code"] == error_code


def test_nfr20_logical_delete(client, producer, owner_engine):
    beat_id = _create(client, producer)
    _set_status(owner_engine, beat_id, "hidden")
    assert client.delete(f"/v1/beats/{beat_id}", headers=auth(producer)).status_code == 204
    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM beats WHERE id = :id"), {"id": beat_id}) == "deleted"
    assert client.get(f"/v1/beats/{beat_id}", headers=auth(producer)).status_code == 404
    assert client.get("/v1/users/me/beats", headers=auth(producer)).json()["items"] == []


# --- FR-8: abandoned uploads ---

def test_fr8_uploading_older_than_24h_becomes_deleted(client, producer, owner_engine):
    old, fresh = _create(client, producer, title="Old beat"), _create(client, producer, title="Fresh beat")
    processing = _create(client, producer, title="Processing beat")
    _set_status(owner_engine, processing, "processing")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET created_at = :t WHERE id IN (:a, :b)"),
                     {"t": datetime.now(UTC) - timedelta(hours=25), "a": old, "b": processing})

    with get_session_factory()() as db:
        assert delete_abandoned_uploads(db) == 1

    with owner_engine.connect() as conn:
        statuses = dict(conn.execute(text("SELECT id, status FROM beats")).all())
    assert statuses == {old: "deleted", fresh: "uploading", processing: "processing"}
