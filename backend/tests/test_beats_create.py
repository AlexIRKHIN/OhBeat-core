"""Creating a beat: FR-1, FR-6, NFR-3, REST API §2.1."""

import httpx
import pytest
from sqlalchemy import text

from tests.helpers import auth, beat_body, make_producer, register


@pytest.fixture
def producer(client):
    return make_producer(client)


def _post(client, tokens, body):
    return client.post("/v1/beats", json=body, headers=auth(tokens))


def _fields(response) -> set[str]:
    return {d["field"] for d in response.json()["details"]}


def test_fr6_create_beat_returns_upload_forms(client, producer, owner_engine):
    response = _post(client, producer, beat_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "uploading"
    assert set(body["uploads"]) == {"wav", "cover", "stems"}
    assert body["uploads"]["wav"]["fields"]["key"] == f"raw/{body['id']}/master.wav"

    with owner_engine.connect() as conn:
        files = dict(conn.execute(text("SELECT kind, storage_key FROM beat_files WHERE beat_id = :id"), {"id": body["id"]}).all())
        prices = conn.scalar(text("SELECT count(*) FROM beat_prices WHERE beat_id = :id"), {"id": body["id"]})
        genres = conn.scalar(text("SELECT count(*) FROM beat_genres WHERE beat_id = :id"), {"id": body["id"]})
    assert files == {
        "master": f"raw/{body['id']}/master.wav",
        "cover": f"raw/{body['id']}/cover.jpg",
        "stems": f"raw/{body['id']}/stems.zip",
    }
    assert (prices, genres) == (4, 1)


def test_fr6_presigned_form_accepts_file_and_s3_enforces_limit(client, producer):
    """The form works for a direct upload; S3 itself rejects a file above content-length-range."""
    form = _post(client, producer, beat_body()).json()["uploads"]["cover"]
    ok = httpx.post(form["url"], data=form["fields"], files={"file": ("cover.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")})
    assert ok.status_code == 204, ok.text
    too_big = httpx.post(form["url"], data=form["fields"], files={"file": ("cover.jpg", b"0" * (5 * 1024 * 1024 + 1), "image/jpeg")})
    assert too_big.status_code == 400
    assert "EntityTooLarge" in too_big.text


def test_fr6_artist_without_producer_role_forbidden(client):
    artist = register(client)
    response = _post(client, artist, beat_body())
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ("title", "ab", False),
        ("title", "abc", True),
        ("title", "  abc  ", True),          # trimmed to 3 characters
        ("title", "x" * 60, True),
        ("title", "x" * 61, False),
        ("bpm", 39, False),
        ("bpm", 40, True),
        ("bpm", 300, True),
        ("bpm", 301, False),
        ("bpm", 120.5, False),
        ("bpm", "120", False),
        ("musical_key", "H", False),
        ("musical_key", "C#m", True),
        ("description", "x" * 1000, True),
        ("description", "x" * 1001, False),
        ("genres", [], False),
        ("genres", ["Trap", "Drill", "Pop"], True),
        ("genres", ["Trap", "Drill", "Pop", "Rock"], False),
        ("genres", ["Trap", "trap"], False),
        ("genres", ["Polka"], False),        # not in the dictionary
    ],
)
def test_fr6_metadata_limits(client, producer, field, value, valid):
    response = _post(client, producer, beat_body(**{field: value}))
    assert response.status_code == (201 if valid else 400), response.text
    if not valid:
        assert any(f.startswith(field) for f in _fields(response))


@pytest.mark.parametrize(
    ("licenses", "valid"),
    [
        ([], False),
        ([{"code": "basic", "price": 99}], False),
        ([{"code": "basic", "price": 100}], True),
        ([{"code": "basic", "price": 500000}], True),
        ([{"code": "basic", "price": 500001}], False),
        ([{"code": "basic", "price": 100}, {"code": "basic", "price": 200}], False),
        ([{"code": "gold", "price": 100}], False),
    ],
)
def test_fr6_license_rules(client, producer, licenses, valid):
    response = _post(client, producer, beat_body(licenses=licenses))
    assert response.status_code == (201 if valid else 400), response.text


@pytest.mark.parametrize("code", ["trackout", "exclusive"])
def test_fr1_stems_required_for_trackout_and_exclusive(client, producer, code):
    body = beat_body(licenses=[{"code": code, "price": 5000}])
    del body["files"]["stems"]
    response = _post(client, producer, body)
    assert response.status_code == 400
    assert "files.stems" in _fields(response)


def test_fr1_stems_optional_for_basic_and_premium(client, producer):
    body = beat_body(licenses=[{"code": "basic", "price": 1500}, {"code": "premium", "price": 3000}])
    del body["files"]["stems"]
    assert _post(client, producer, body).status_code == 201


@pytest.mark.parametrize(
    ("file", "change", "bad_field"),
    [
        ("wav", {"name": "track.mp3"}, "files.wav.name"),
        ("wav", {"content_type": "audio/mpeg"}, "files.wav.content_type"),
        ("wav", {"size_bytes": 200 * 1024 * 1024 + 1}, "files.wav.size_bytes"),
        ("stems", {"size_bytes": 1024 * 1024 * 1024 + 1}, "files.stems.size_bytes"),
        ("stems", {"name": "stems.rar"}, "files.stems.name"),
        ("cover", {"size_bytes": 5 * 1024 * 1024 + 1}, "files.cover.size_bytes"),
        ("cover", {"content_type": "image/gif", "name": "c.gif"}, "files.cover.content_type"),
        ("cover", {"name": "cover.png"}, "files.cover.name"),  # extension disagrees with image/jpeg
    ],
)
def test_fr6_declared_file_checks(client, producer, file, change, bad_field):
    body = beat_body()
    body["files"][file].update(change)
    response = _post(client, producer, body)
    assert response.status_code == 400
    assert bad_field in _fields(response)


@pytest.mark.parametrize("content_type", ["audio/x-wav", "audio/wave"])
def test_gap17_browser_wav_mime_variants_accepted(client, producer, content_type):
    body = beat_body()
    body["files"]["wav"]["content_type"] = content_type
    assert _post(client, producer, body).status_code == 201


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "My BADWORD beat"),
        ("title", "Запрещенка vibes"),       # "ё" written as "е"
        ("description", "a spamword here"),
    ],
)
def test_fr6_stop_list(client, producer, field, value):
    response = _post(client, producer, beat_body(**{field: value}))
    assert response.status_code == 400
    detail = next(d for d in response.json()["details"] if d["field"] == field)
    assert detail["issue"] == "Запрещенное слово"


def test_fr6_stop_list_matches_whole_words_only(client, producer):
    assert _post(client, producer, beat_body(title="Badwordless groove")).status_code == 201
