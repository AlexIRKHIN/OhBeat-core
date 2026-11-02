"""Development seeds: genres, licenses and three test accounts.

Run under the schema owner after migrations (docker compose service `migrate`).
Idempotent: a second run changes nothing. Logins and passwords are in .env (SEED_*).
"""

import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

from app.common.security import hash_password

GENRES = [
    "Afrobeats", "Boom Bap", "Drill", "Hip-Hop", "House", "Lo-Fi",
    "Pop", "R&B", "Reggaeton", "Rock", "Synthwave", "Trap",
]

# Files per license — User_Stories.md §2.2
LICENSES = [
    # code, name, mp3, wav, stems, exclusive
    ("basic", "Basic Lease", True, False, False, False),
    ("premium", "Premium Lease", True, True, False, False),
    ("trackout", "Trackout Lease", True, True, True, False),
    ("exclusive", "Exclusive", True, True, True, True),
]


def ensure_user(conn, email: str, password: str, display_name: str, roles: list[str]) -> int:
    user_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar()
    if user_id is None:
        user_id = conn.execute(
            text("INSERT INTO users (email, password_hash, pd_consent_at) VALUES (:e, :h, :now) RETURNING id"),
            {"e": email, "h": hash_password(password), "now": datetime.now(UTC)},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO profiles (user_id, display_name) VALUES (:u, :n)"), {"u": user_id, "n": display_name}
        )
    for role in roles:
        conn.execute(
            text("INSERT INTO user_roles (user_id, role) VALUES (:u, :r) ON CONFLICT DO NOTHING"),
            {"u": user_id, "r": role},
        )
    return user_id


# ASSUMPTION: GAP-57 — demo entries so the stop-list check can be seen; the real list is kept by the Administrator
STOP_WORDS = ["запрещёнка", "badword", "spamword"]


def seed_dictionaries(conn) -> None:
    for word in STOP_WORDS:
        conn.execute(text("INSERT INTO stop_words (word) VALUES (:w) ON CONFLICT (word) DO NOTHING"), {"w": word})
    for name in GENRES:
        conn.execute(text("INSERT INTO genres (name) VALUES (:n) ON CONFLICT (name) DO NOTHING"), {"n": name})
    for code, name, mp3, wav, stems, excl in LICENSES:
        conn.execute(
            text(
                "INSERT INTO licenses (code, name, includes_mp3, includes_wav, includes_stems, is_exclusive) "
                "VALUES (:c, :n, :mp3, :wav, :stems, :excl) ON CONFLICT (code) DO NOTHING"
            ),
            {"c": code, "n": name, "mp3": mp3, "wav": wav, "stems": stems, "excl": excl},
        )


def main() -> None:
    engine = create_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    with engine.begin() as conn:
        seed_dictionaries(conn)

        ensure_user(conn, os.environ["SEED_ARTIST_EMAIL"], os.environ["SEED_ARTIST_PASSWORD"], "Test Artist", ["artist"])
        ensure_user(conn, os.environ["SEED_ADMIN_EMAIL"], os.environ["SEED_ADMIN_PASSWORD"], "Administrator", ["admin"])

        producer_id = ensure_user(
            conn, os.environ["SEED_PRODUCER_EMAIL"], os.environ["SEED_PRODUCER_PASSWORD"],
            "Test Producer", ["artist", "producer"],
        )
        # A producer is complete only with contract details and a seller id in YooKassa (FR-33)
        conn.execute(
            text(
                "INSERT INTO billing_profiles (user_id, payer_type, last_name, first_name, email, phone) "
                "VALUES (:u, 'individual', 'Петров', 'Пётр', :e, '+79000000001') ON CONFLICT DO NOTHING"
            ),
            {"u": producer_id, "e": os.environ["SEED_PRODUCER_EMAIL"]},
        )
        conn.execute(
            text(
                "INSERT INTO producer_accounts (user_id, tax_status, yookassa_account_id, pep_agreement_at) "
                "VALUES (:u, 'self_employed', :acc, now()) ON CONFLICT DO NOTHING"
            ),
            {"u": producer_id, "acc": os.environ["SEED_PRODUCER_YOOKASSA_ACCOUNT_ID"]},
        )
    print("Seeds applied")


if __name__ == "__main__":
    main()
