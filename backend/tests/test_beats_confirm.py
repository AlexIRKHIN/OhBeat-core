"""Upload confirmation and the transactional outbox: FR-6 (new forms), FR-7, REST API §2.2."""

import httpx
from sqlalchemy import text

from tests.helpers import auth, beat_body, make_producer


def _upload(form: dict, data: bytes, name: str) -> None:
    """What the browser does: multipart POST straight to S3."""
    response = httpx.post(form["url"], data=form["fields"], files={"file": (name, data)})
    assert response.status_code == 204, response.text


def _create(client, tokens, **overrides) -> dict:
    response = client.post("/v1/beats", json=beat_body(**overrides), headers=auth(tokens))
    assert response.status_code == 201, response.text
    return response.json()


def _upload_all(created: dict) -> None:
    uploads = created["uploads"]
    _upload(uploads["wav"], b"RIFF....WAVE" + b"0" * 1000, "master.wav")
    _upload(uploads["cover"], b"\xff\xd8\xff" + b"0" * 1000, "cover.jpg")
    if "stems" in uploads:
        _upload(uploads["stems"], b"PK\x03\x04" + b"0" * 1000, "stems.zip")


def test_fr7_confirm_without_files_lists_missing(client):
    producer = make_producer(client)
    created = _create(client, producer)
    _upload(created["uploads"]["wav"], b"RIFF" + b"0" * 100, "master.wav")

    response = client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(producer))
    assert response.status_code == 422
    assert response.json()["error_code"] == "FILES_MISSING"
    assert {d["field"] for d in response.json()["details"]} == {"files.cover", "files.stems"}


def test_fr7_confirm_moves_to_processing_and_writes_outbox_in_one_transaction(client, owner_engine):
    producer = make_producer(client)
    created = _create(client, producer)
    _upload_all(created)

    response = client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(producer))
    assert response.status_code == 202, response.text
    assert response.json() == {"id": created["id"], "status": "processing"}

    with owner_engine.connect() as conn:
        status = conn.scalar(text("SELECT status FROM beats WHERE id = :id"), {"id": created["id"]})
        event = conn.execute(text("SELECT id, event_type, payload, published_at FROM outbox")).one()
        sizes = dict(conn.execute(
            text("SELECT kind, size_bytes FROM beat_files WHERE beat_id = :id"), {"id": created["id"]}
        ).all())
    assert status == "processing"
    assert event.event_type == "beat.media.process"
    assert event.published_at is None  # the relay has not run yet
    payload = event.payload
    # Fields of the command message, RabbitMQ_Worker.md §3
    assert payload["event_id"] == str(event.id)
    assert payload["beat_id"] == created["id"]
    assert payload["files"] == {
        "wav_key": f"raw/{created['id']}/master.wav",
        "stems_key": f"raw/{created['id']}/stems.zip",
        "cover_key": f"raw/{created['id']}/cover.jpg",
    }
    assert payload["options"] == {"voice_tag": True, "tag_interval_sec": 20}
    # Declared sizes are replaced with the real ones from HeadObject
    assert sizes["master"] == 1012


def test_fr7_stems_key_is_null_without_stems(client, owner_engine):
    producer = make_producer(client)
    body = beat_body(licenses=[{"code": "basic", "price": 1500}])
    del body["files"]["stems"]
    created = client.post("/v1/beats", json=body, headers=auth(producer)).json()
    _upload_all(created)
    assert client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(producer)).status_code == 202
    with owner_engine.connect() as conn:
        payload = conn.scalar(text("SELECT payload FROM outbox"))
    assert payload["files"]["stems_key"] is None


def test_fr7_second_confirm_is_invalid_status(client, owner_engine):
    producer = make_producer(client)
    created = _create(client, producer)
    _upload_all(created)
    assert client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(producer)).status_code == 202
    again = client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(producer))
    assert again.status_code == 409
    assert again.json()["error_code"] == "INVALID_STATUS"
    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM outbox")) == 1


def test_confirm_someone_elses_beat_forbidden(client):
    owner = make_producer(client, email="owner@example.com")
    other = make_producer(client, email="other@example.com")
    created = _create(client, owner)
    response = client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(other))
    assert response.status_code == 403


def test_fr6_new_upload_forms_while_uploading(client):
    producer = make_producer(client)
    created = _create(client, producer)
    response = client.post(f"/v1/beats/{created['id']}/uploads", json={"files": ["wav", "stems"]}, headers=auth(producer))
    assert response.status_code == 200, response.text
    uploads = response.json()["uploads"]
    assert set(uploads) == {"wav", "stems"}
    assert uploads["wav"]["fields"]["key"] == f"raw/{created['id']}/master.wav"
    _upload(uploads["wav"], b"RIFF" + b"0" * 10, "master.wav")


def test_fr6_new_upload_forms_only_while_uploading(client):
    producer = make_producer(client)
    created = _create(client, producer)
    _upload_all(created)
    client.post(f"/v1/beats/{created['id']}/confirm", headers=auth(producer))
    response = client.post(f"/v1/beats/{created['id']}/uploads", json={"files": ["wav"]}, headers=auth(producer))
    assert response.status_code == 409


def test_fr6_new_upload_form_for_undeclared_file(client):
    producer = make_producer(client)
    body = beat_body(licenses=[{"code": "basic", "price": 1500}])
    del body["files"]["stems"]
    created = client.post("/v1/beats", json=body, headers=auth(producer)).json()
    response = client.post(f"/v1/beats/{created['id']}/uploads", json={"files": ["stems"]}, headers=auth(producer))
    assert response.status_code == 400
