"""Administration: FR-35 … FR-37, NFR-32, REST API §2.13; GAP-16, GAP-21, GAP-74 … GAP-76."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.catalog.media_results import apply_result
from app.common.db import get_session_factory
from app.common.storage import get_storage
from app.main import app
from app.notifications.service import get_notifier
from tests.helpers import STRONG_PASSWORD, auth, beat_body, make_producer, register
from tests.test_signature import FakeNotifier


@pytest.fixture
def admin(client, owner_engine):
    """A user with the role `admin`; a fresh login puts the role into the token."""
    register(client, email="admin@example.com")
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO user_roles (user_id, role) SELECT id, 'admin' FROM users WHERE email = 'admin@example.com'"))
    return client.post("/v1/auth/login", json={"email": "admin@example.com", "password": STRONG_PASSWORD}).json()


@pytest.fixture(autouse=True)
def own_dictionary_entries(owner_engine):
    """Dictionaries are not emptied between tests (only users and what refers to them): the genres
    a test adds are removed afterwards, so another test can add the same name."""
    yield
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM genres WHERE name IN ('Jersey Club', 'Hyperpop', 'Phonk Test') "
                          "AND id NOT IN (SELECT genre_id FROM beat_genres)"))


@pytest.fixture
def producer(client):
    return make_producer(client)


@pytest.fixture
def mail():
    notifier = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: notifier
    yield notifier
    app.dependency_overrides.pop(get_notifier, None)


# --- Access (REST API §2.13) ---

ENDPOINTS = [
    ("get", "/v1/admin/audit-log", None),
    ("get", "/v1/admin/audit-log/facets", None),
    ("get", "/v1/admin/genres", None),
    ("post", "/v1/admin/genres", {"name": "Phonk"}),
    ("delete", "/v1/admin/genres/1", None),
    ("get", "/v1/admin/stop-words", None),
    ("post", "/v1/admin/stop-words", {"word": "плохо"}),
    ("delete", "/v1/admin/stop-words/1", None),
    ("get", "/v1/admin/beats", None),
    ("post", "/v1/admin/beats/1/reprocess", None),
    ("post", "/v1/admin/beats/1/reject", {"reason": "Нарушение правил"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_admin_only(client, producer, method, path, body):
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers=auth(producer), **kwargs).status_code == 403  # Producer and Artist


# --- Audit Log (FR-35, NFR-32, GAP-75) ---

def _entry(conn, action: str, entity: str, entity_id: int, at: datetime) -> None:
    conn.execute(text("INSERT INTO audit_log (occurred_at, action, entity, entity_id, details) "
                      "VALUES (:at, :a, :e, :id, '{\"k\": 1}')"), {"at": at, "a": action, "e": entity, "id": entity_id})


def _actions(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [i["action"] for i in response.json()["items"]]


def test_fr35_filters_by_action_entity_and_moscow_period(client, admin, owner_engine):
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log"))
        _entry(conn, "payment.created", "order", 7, datetime(2026, 10, 1, 10, 0, tzinfo=UTC))
        _entry(conn, "payment.succeeded", "order", 7, datetime(2026, 10, 1, 21, 30, tzinfo=UTC))  # 02.10 00:30 МСК
        _entry(conn, "order.created", "order", 8, datetime(2026, 10, 2, 9, 0, tzinfo=UTC))
        _entry(conn, "admin.genre_created", "genre", 3, datetime(2026, 10, 3, 9, 0, tzinfo=UTC))
    get = lambda **p: client.get("/v1/admin/audit-log", params=p, headers=auth(admin))  # noqa: E731

    assert _actions(get(action="payment.succeeded")) == ["payment.succeeded"]
    assert _actions(get(action="payment.")) == ["payment.succeeded", "payment.created"]  # a group, newest first
    assert _actions(get(entity="order", entity_id=7)) == ["payment.succeeded", "payment.created"]
    # 21:30 UTC on 1 October is already 2 October in Moscow
    assert _actions(get(**{"from": "2026-10-02", "to": "2026-10-02"})) == ["order.created", "payment.succeeded"]
    assert get(**{"from": "2026-10-03", "to": "2026-10-01"}).status_code == 400

    facets = client.get("/v1/admin/audit-log/facets", headers=auth(admin)).json()
    assert facets["entities"] == ["genre", "order"] and "payment.created" in facets["actions"]


def test_fr35_pages_have_no_gaps_and_no_repeats(client, admin, owner_engine):
    same = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log"))
        for i in range(7):
            _entry(conn, "order.created", "order", i, same)  # equal times: the id decides the order
    seen, cursor = [], None
    while True:
        body = client.get("/v1/admin/audit-log", params={"limit": 3, **({"cursor": cursor} if cursor else {})},
                          headers=auth(admin)).json()
        seen += [i["entity_id"] for i in body["items"]]
        if not (cursor := body["next_cursor"]):
            break
    assert sorted(seen) == list(range(7)) and len(seen) == 7


def test_fr35_entry_shows_actor_and_details(client, admin):
    client.post("/v1/admin/genres", json={"name": "Phonk Test"}, headers=auth(admin))
    entry = client.get("/v1/admin/audit-log", params={"action": "admin.genre_created"}, headers=auth(admin)).json()["items"][0]
    assert entry["actor"]["email"] == "admin@example.com" and entry["details"] == {"name": "Phonk Test"}


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_nfr32_audit_log_cannot_be_changed_through_the_api(client, admin, method):
    assert getattr(client, method)("/v1/admin/audit-log", headers=auth(admin)).status_code == 405


# --- Genres (FR-36, GAP-76) ---

def test_fr36_add_genre_appears_in_the_forms(client, admin):
    created = client.post("/v1/admin/genres", json={"name": "  Jersey   Club  "}, headers=auth(admin))
    assert created.status_code == 201 and created.json()["name"] == "Jersey Club"
    assert "Jersey Club" in [g["name"] for g in client.get("/v1/dictionaries").json()["genres"]]
    duplicate = client.post("/v1/admin/genres", json={"name": "JERSEY CLUB"}, headers=auth(admin))
    assert (duplicate.status_code, duplicate.json()["error_code"]) == (409, "DUPLICATE")
    assert client.post("/v1/admin/genres", json={"name": "x"}, headers=auth(admin)).status_code == 400


def test_fr36_unused_genre_is_deleted_with_an_audit_entry(client, admin, owner_engine):
    genre_id = client.post("/v1/admin/genres", json={"name": "Hyperpop"}, headers=auth(admin)).json()["id"]
    assert client.delete(f"/v1/admin/genres/{genre_id}", headers=auth(admin)).status_code == 204
    assert client.delete(f"/v1/admin/genres/{genre_id}", headers=auth(admin)).status_code == 404
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'admin.genre_deleted'")).scalar() == 1


def test_fr36_used_genre_cannot_be_deleted_even_by_a_deleted_beat(client, admin, producer, owner_engine):
    beat_id = client.post("/v1/beats", json=beat_body(), headers=auth(producer)).json()["id"]  # Synthwave
    genres = {g["name"]: g for g in client.get("/v1/admin/genres", headers=auth(admin)).json()}
    assert genres["Synthwave"]["beats_count"] == 1
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'deleted' WHERE id = :b"), {"b": beat_id})
    response = client.delete(f"/v1/admin/genres/{genres['Synthwave']['id']}", headers=auth(admin))
    assert (response.status_code, response.json()["error_code"]) == (409, "GENRE_IN_USE")
    assert response.json()["details"][0]["beats_count"] == 1


# --- Stop-list (FR-36, GAP-16, GAP-76) ---

def test_fr36_stop_word_works_at_once_and_is_normalized(client, admin, producer):
    created = client.post("/v1/admin/stop-words", json={"word": "  Ёжик "}, headers=auth(admin))
    assert created.status_code == 201 and created.json()["word"] == "ежик"
    blocked = client.post("/v1/beats", json=beat_body(title="Мой ЕЖИК"), headers=auth(producer))
    assert blocked.status_code == 400 and blocked.json()["details"][0]["field"] == "title"

    assert client.post("/v1/admin/stop-words", json={"word": "ЕЖИК"}, headers=auth(admin)).status_code == 409
    for bad in ("a", "ok!", "a_b"):
        assert client.post("/v1/admin/stop-words", json={"word": bad}, headers=auth(admin)).status_code == 400

    word_id = created.json()["id"]
    assert client.delete(f"/v1/admin/stop-words/{word_id}", headers=auth(admin)).status_code == 204
    assert client.post("/v1/beats", json=beat_body(title="Мой ЕЖИК"), headers=auth(producer)).status_code == 201


def test_fr36_stop_phrase_of_several_words(client, admin, producer):
    created = client.post("/v1/admin/stop-words", json={"word": "Очень  Плохо"}, headers=auth(admin)).json()
    assert created["word"] == "очень плохо"
    assert client.post("/v1/beats", json=beat_body(title="Очень плохо"), headers=auth(producer)).status_code == 400
    assert client.post("/v1/beats", json=beat_body(title="Очень хорошо"), headers=auth(producer)).status_code == 201
    client.delete(f"/v1/admin/stop-words/{created['id']}", headers=auth(admin))  # dictionaries outlive the test


# --- Stuck beats (FR-37, GAP-21, GAP-74) ---

def _processing(client, producer, owner_engine, minutes_ago: int, title: str = "Stuck one") -> int:
    """A beat in `processing` whose task went to the outbox `minutes_ago` minutes ago."""
    from app.catalog.models import Beat
    from app.catalog.service import enqueue_processing

    beat_id = client.post("/v1/beats", json=beat_body(title=title), headers=auth(producer)).json()["id"]
    with get_session_factory()() as db:
        beat = db.get(Beat, beat_id)
        beat.status = "processing"
        enqueue_processing(db, beat)
        db.commit()
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE outbox SET created_at = now() - make_interval(mins => :m) "
                          "WHERE (payload->>'beat_id')::bigint = :b"), {"m": minutes_ago, "b": beat_id})
    return beat_id


def _tasks(owner_engine, beat_id: int):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT payload, created_at FROM outbox WHERE event_type = 'beat.media.process' "
                                 "AND (payload->>'beat_id')::bigint = :b ORDER BY created_at"), {"b": beat_id}).all()


def test_fr37_only_beats_processing_longer_than_30_minutes_are_stuck(client, admin, producer, owner_engine):
    stuck = _processing(client, producer, owner_engine, 31, "Stuck one")
    fresh = _processing(client, producer, owner_engine, 5, "Fresh one")
    listed = client.get("/v1/admin/beats", params={"status": "processing"}, headers=auth(admin)).json()
    assert [(b["id"], b["stuck"], b["producer"]) for b in listed] == [(stuck, True, "Ivan Artist")]
    everything = client.get("/v1/admin/beats", params={"all": "true"}, headers=auth(admin)).json()
    assert {b["id"]: b["stuck"] for b in everything} == {stuck: True, fresh: False}
    since = datetime.fromisoformat(listed[0]["processing_since"])
    assert timedelta(minutes=30) < datetime.now(UTC) - since < timedelta(minutes=32)


def test_fr37_reprocess_adds_the_same_task_and_resets_the_clock(client, admin, producer, owner_engine):
    beat_id = _processing(client, producer, owner_engine, 31)
    response = client.post(f"/v1/admin/beats/{beat_id}/reprocess", headers=auth(admin))
    assert response.status_code == 202 and response.json()["status"] == "processing"

    first, second = _tasks(owner_engine, beat_id)
    assert second.payload["files"] == first.payload["files"] and second.payload["options"] == first.payload["options"]
    assert second.payload["event_id"] != first.payload["event_id"]  # a new message, not the one in the DLQ
    assert client.get("/v1/admin/beats", headers=auth(admin)).json() == []  # GAP-74: counted from the new task
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'admin.beat_reprocessed'")).scalar() == 1


def test_fr37_reject_with_reason_emails_the_producer(client, admin, producer, owner_engine, mail):
    beat_id = _processing(client, producer, owner_engine, 31)
    assert client.post(f"/v1/admin/beats/{beat_id}/reject", json={"reason": "ок"}, headers=auth(admin)).status_code == 400
    response = client.post(f"/v1/admin/beats/{beat_id}/reject", json={"reason": "Стемы повреждены"}, headers=auth(admin))
    assert response.status_code == 200 and response.json()["status"] == "rejected"

    beat = client.get(f"/v1/beats/{beat_id}", headers=auth(producer)).json()
    assert (beat["status"], beat["rejection_reason"]) == ("rejected", "Стемы повреждены")  # FR-34: seen in My beats
    assert mail.emails[-1][0] == "producer@example.com" and "Стемы повреждены" in mail.emails[-1][2]
    with owner_engine.connect() as conn:
        details = conn.execute(text("SELECT details FROM audit_log WHERE action = 'admin.beat_rejected'")).scalar()
    assert details["reason"] == "Стемы повреждены"


def test_fr37_late_worker_result_after_the_decision_is_ignored(client, admin, producer, owner_engine, mail):
    beat_id = _processing(client, producer, owner_engine, 31)
    client.post(f"/v1/admin/beats/{beat_id}/reject", json={"reason": "Решение администратора"}, headers=auth(admin))
    late = {"event_id": "late", "beat_id": beat_id, "result": "processed", "outputs": {}}
    with get_session_factory()() as db:
        assert apply_result(db, get_storage(), mail, late).status == "skipped"
    assert client.get(f"/v1/beats/{beat_id}", headers=auth(producer)).json()["status"] == "rejected"


@pytest.mark.parametrize("status", ["active", "rejected", "uploading"])
def test_fr37_actions_only_for_processing(client, admin, producer, owner_engine, status):
    beat_id = client.post("/v1/beats", json=beat_body(), headers=auth(producer)).json()["id"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = :s WHERE id = :b"), {"s": status, "b": beat_id})
    for path, body in (("reprocess", None), ("reject", {"reason": "Причина отказа"})):
        response = client.post(f"/v1/admin/beats/{beat_id}/{path}", json=body, headers=auth(admin))
        assert (response.status_code, response.json()["error_code"]) == (409, "INVALID_STATUS")
    assert client.post("/v1/admin/beats/999999/reprocess", headers=auth(admin)).status_code == 404
