"""Stop-list check of the title and description (FR-6, FR-36).

ASSUMPTION: GAP-16 — case-insensitive, whole words only, "ё" equals "е".
A stop entry may be a phrase of several words.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import StopWord


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def contains_stop_word(text: str, words: list[str]) -> bool:
    normalized = normalize(text)
    for word in words:
        # (?<!\w) / (?!\w): the word must not be a part of a longer word
        if re.search(rf"(?<!\w){re.escape(normalize(word))}(?!\w)", normalized):
            return True
    return False


def load_stop_words(db: Session) -> list[str]:
    return list(db.scalars(select(StopWord.word)))
