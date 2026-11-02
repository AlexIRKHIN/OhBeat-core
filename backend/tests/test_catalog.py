"""Public catalog, producer page and preview streaming: REST API §2.3, §2.9; US-A1, US-A2, US-P5;
FR-19, FR-24 (sold beats hidden), RFC_Audio_Streaming.md §3."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.common.config import get_settings
from app.common.storage import _client
from tests.helpers import auth, beat_body, make_producer, register

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def producer(client):
    return make_producer(client)


def _publish(client, owner_engine, tokens, minutes: int, status: str = "active", **overrides) -> int:
    """A beat created through the API and put into a catalog state (processing is covered by slice 1 tests).
    `minutes` sets the publication time, so the order is predictable."""
    beat_id = client.post("/v1/beats", json=beat_body(**overrides), headers=auth(tokens)).json()["id"]
    with owner_engine.begin() as conn:
        if status == "reserved":
            conn.execute(text("INSERT INTO orders (customer_id, status, total_amount, billing_snapshot) "
                              "SELECT id, 'pending', 100, '{}' FROM users LIMIT 1"))
            conn.execute(text("UPDATE beats SET status = 'reserved', reserved_order_id = (SELECT max(id) FROM orders), "
                              "reserved_until = now() + interval '15 minutes' WHERE id = :id"), {"id": beat_id})
        else:
            conn.execute(text("UPDATE beats SET status = :s WHERE id = :id"), {"s": status, "id": beat_id})
        conn.execute(text("UPDATE beats SET published_at = :t WHERE id = :id"),
                     {"t": T0 + timedelta(minutes=minutes), "id": beat_id})
    return beat_id


def _ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


# --- What the catalog shows ---

def test_catalog_is_public_and_newest_first(client, producer, owner_engine):
    old = _publish(client, owner_engine, producer, 1, title="Old one")
    new = _publish(client, owner_engine, producer, 2, title="New one")
    assert _ids(client.get("/v1/beats")) == [new, old]


def test_only_active_and_reserved_are_shown(client, producer, owner_engine):
    active = _publish(client, owner_engine, producer, 1)
    reserved = _publish(client, owner_engine, producer, 2, status="reserved")
    for i, status in enumerate(["uploading", "processing", "rejected", "hidden", "sold", "deleted"]):
        _publish(client, owner_engine, producer, 10 + i, status=status)

    items = client.get("/v1/beats").json()["items"]
    assert [i["id"] for i in items] == [reserved, active]
    assert {i["id"]: i["is_reserved"] for i in items} == {reserved: True, active: False}  # FR-19


def test_card_fields_and_prices_without_fee(client, producer, owner_engine):
    beat_id = _publish(client, owner_engine, producer, 1)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beat_prices SET is_active = false WHERE beat_id = :id AND license_id = "
                          "(SELECT id FROM licenses WHERE code = 'premium')"), {"id": beat_id})
    card = client.get("/v1/beats").json()["items"][0]
    assert card["producer"]["display_name"] == "Ivan Artist"
    assert card["genres"] == ["Synthwave"]
    # Only active licenses, the Producer's own prices (FR-15: the fee is added in the cart)
    assert [(lic["code"], lic["price"]) for lic in card["licenses"]] == [("basic", 1500), ("trackout", 6000), ("exclusive", 25000)]
    assert card["status"] is None and card["rejection_reason"] is None  # owner-only fields are hidden


# --- Filters (US-A2) ---

@pytest.fixture
def variety(client, producer, owner_engine) -> dict[str, int]:
    return {
        "trap90": _publish(client, owner_engine, producer, 1, genres=["Trap"], bpm=90, musical_key="Am",
                           licenses=[{"code": "basic", "price": 1000}]),
        "trap140": _publish(client, owner_engine, producer, 2, genres=["Trap", "Drill"], bpm=140, musical_key="Cm",
                            licenses=[{"code": "basic", "price": 3000}, {"code": "exclusive", "price": 20000}]),
        "pop120": _publish(client, owner_engine, producer, 3, genres=["Pop"], bpm=120, musical_key="Am",
                           licenses=[{"code": "premium", "price": 2500}]),
    }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("genre=Trap", ["trap140", "trap90"]),
        ("genre=trap", ["trap140", "trap90"]),       # case-insensitive
        ("genre=Drill", ["trap140"]),
        ("bpm_min=100", ["pop120", "trap140"]),
        ("bpm_max=120", ["pop120", "trap90"]),
        ("bpm_min=100&bpm_max=130", ["pop120"]),
        ("musical_key=Am", ["pop120", "trap90"]),
        ("price_max=2500", ["pop120", "trap90"]),
        ("genre=Trap&musical_key=Am&price_max=1000", ["trap90"]),
        ("genre=Polka", []),                         # GAP-59: an unknown genre is an empty page
    ],
)
def test_us_a2_filters(client, variety, query, expected):
    by_id = {v: k for k, v in variety.items()}
    assert [by_id[i] for i in _ids(client.get(f"/v1/beats?{query}"))] == expected


def test_price_max_uses_lowest_active_price(client, producer, owner_engine):
    """REST API §2.3: an inactive cheap license does not make the beat match."""
    beat_id = _publish(client, owner_engine, producer, 1,
                       licenses=[{"code": "basic", "price": 500}, {"code": "premium", "price": 4000}])
    assert _ids(client.get("/v1/beats?price_max=1000")) == [beat_id]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beat_prices SET is_active = false WHERE beat_id = :id AND price = 500"), {"id": beat_id})
    assert _ids(client.get("/v1/beats?price_max=1000")) == []
    assert _ids(client.get("/v1/beats?price_max=4000")) == [beat_id]


@pytest.mark.parametrize(
    "query",
    ["bpm_min=39", "bpm_max=301", "bpm_min=130&bpm_max=100", "musical_key=H", "price_max=-1",
     "sort=cheapest", "limit=0", "limit=51", "cursor=not-a-cursor"],
)
def test_gap59_invalid_filters_are_400(client, query):
    response = client.get(f"/v1/beats?{query}")
    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


# --- Cursor pagination ---

def test_cursor_pages_without_gaps_or_duplicates(client, producer, owner_engine):
    ids = [_publish(client, owner_engine, producer, i, title=f"Beat {i}") for i in range(5)]
    first = client.get("/v1/beats?limit=2").json()
    second = client.get(f"/v1/beats?limit=2&cursor={first['next_cursor']}").json()
    third = client.get(f"/v1/beats?limit=2&cursor={second['next_cursor']}").json()
    seen = [i["id"] for page in (first, second, third) for i in page["items"]]
    assert seen == list(reversed(ids))
    assert third["next_cursor"] is None


def test_cursor_is_stable_when_new_beats_appear(client, producer, owner_engine):
    """REST API §2.3: a beat published between two page requests does not shift the next page."""
    ids = [_publish(client, owner_engine, producer, i, title=f"Beat {i}") for i in range(4)]
    first = client.get("/v1/beats?limit=2").json()
    newest = _publish(client, owner_engine, producer, 100, title="Brand new")
    second = client.get(f"/v1/beats?limit=2&cursor={first['next_cursor']}").json()
    assert [i["id"] for i in first["items"]] == [ids[3], ids[2]]
    assert [i["id"] for i in second["items"]] == [ids[1], ids[0]]
    assert _ids(client.get("/v1/beats?limit=1")) == [newest]


def test_gap61_returned_beat_keeps_its_place(client, producer, owner_engine):
    older = _publish(client, owner_engine, producer, 1, title="Older")
    newer = _publish(client, owner_engine, producer, 2, title="Newer")
    client.patch(f"/v1/beats/{older}", json={"status": "hidden"}, headers=auth(producer))
    client.patch(f"/v1/beats/{older}", json={"status": "active"}, headers=auth(producer))
    assert _ids(client.get("/v1/beats")) == [newer, older]


# --- Producer page (US-P5, REST API §2.9) ---

def test_producer_page_with_profile_and_only_own_beats(client, producer, owner_engine):
    mine = _publish(client, owner_engine, producer, 1, genres=["Trap"])
    other = make_producer(client, email="other@example.com")
    _publish(client, owner_engine, other, 2)
    hidden = _publish(client, owner_engine, producer, 3, status="hidden")
    client.put("/v1/users/me", json={"display_name": "Kirill Beats", "bio": "Trap from Moscow"}, headers=auth(producer))
    producer_id = client.get("/v1/users/me", headers=auth(producer)).json()["id"]

    page = client.get(f"/v1/producers/{producer_id}").json()
    assert (page["display_name"], page["bio"]) == ("Kirill Beats", "Trap from Moscow")
    assert [i["id"] for i in page["items"]] == [mine]
    assert hidden not in [i["id"] for i in page["items"]]
    # The same filters as the catalog
    assert client.get(f"/v1/producers/{producer_id}?genre=Pop").json()["items"] == []


def test_gap58_producer_page_404_for_non_producer(client):
    artist = register(client)
    artist_id = client.get("/v1/users/me", headers=auth(artist)).json()["id"]
    assert client.get(f"/v1/producers/{artist_id}").status_code == 404
    assert client.get("/v1/producers/999999").status_code == 404


# --- Preview streaming (RFC_Audio_Streaming.md §3) ---

def test_preview_served_in_parts_with_206(test_buckets):
    """MinIO (our CDN) answers Range requests with 206 and the total size in Content-Range."""
    settings = get_settings()
    data = bytes(range(256)) * 4000  # 1 024 000 bytes
    s3 = _client(settings.s3_internal_endpoint)
    s3.put_object(Bucket=settings.bucket_public, Key="previews/1_v1.mp3", Body=data, ContentType="audio/mpeg",
                  CacheControl="public, max-age=31536000, immutable")
    url = f"{settings.s3_internal_endpoint}/{settings.bucket_public}/previews/1_v1.mp3"

    start = httpx.get(url, headers={"Range": "bytes=0-"})
    assert start.status_code == 206
    assert start.headers["content-range"] == f"bytes 0-{len(data) - 1}/{len(data)}"

    seek = httpx.get(url, headers={"Range": "bytes=512000-"})  # "rewind to the middle" (RFC §3.2)
    assert seek.status_code == 206
    assert seek.headers["content-range"] == f"bytes 512000-{len(data) - 1}/{len(data)}"
    assert seek.content == data[512000:]
    assert seek.headers["accept-ranges"] == "bytes"
    assert seek.headers["cache-control"] == "public, max-age=31536000, immutable"
