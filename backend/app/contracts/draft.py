"""Text of the license contract (FR-26, RFC ПЭП §3).

The draft is built only from frozen data — the billing snapshot of the order (buyer and licensors,
GAP-8), the order item and the license — so the same data always gives the same text and the same
`draft_sha256` (GAP-9). The signature mark is NOT part of the draft: it is added to the final PDF.

ASSUMPTION: GAP-31 — the legal wording is a placeholder until a lawyer reviews it.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,  # a missing value is an error, not an empty place in a legal text
    keep_trailing_newline=True,
)

# Terms per license (User_Stories.md §2.2). Placeholder wording (GAP-31).
TERMS = {
    "basic": {
        "nature": "простую (неисключительную) лицензию",
        "lines": [
            "Бит может использоваться для создания одного производного музыкального произведения.",
            "Тираж и количество прослушиваний ограничиваются условиями типовой лицензии Basic.",
            "Лицензиар сохраняет право предоставлять лицензии на бит третьим лицам.",
        ],
    },
    "premium": {
        "nature": "простую (неисключительную) лицензию",
        "lines": [
            "Бит может использоваться для создания одного производного музыкального произведения.",
            "Тираж и количество прослушиваний ограничиваются условиями типовой лицензии Premium.",
            "Лицензиар сохраняет право предоставлять лицензии на бит третьим лицам.",
        ],
    },
    "trackout": {
        "nature": "простую (неисключительную) лицензию",
        "lines": [
            "Бит и отдельные дорожки (стемы) могут использоваться для создания и сведения одного производного произведения.",
            "Тираж и количество прослушиваний ограничиваются условиями типовой лицензии Trackout.",
            "Лицензиар сохраняет право предоставлять лицензии на бит третьим лицам.",
        ],
    },
    "exclusive": {
        "nature": "исключительную лицензию",
        "lines": [
            "Лицензиат получает исключительное право использования бита без ограничения тиража.",
            "После оплаты бит снимается с продажи на платформе навсегда.",
            "Ранее выданные неисключительные лицензии третьим лицам сохраняют силу.",
        ],
    },
}

SIGNATURE_CLAUSE = {
    # RFC ПЭП §2
    "offer_accept": "Договор заключается акцептом публичной оферты (п. 3 ст. 438 ГК РФ) из авторизованной учётной записи Лицензиата.",
    "otp": "Договор подписывается простой электронной подписью Лицензиата одноразовым кодом из SMS (63-ФЗ) по соглашению о ПЭП.",
}


@dataclass(frozen=True)
class DraftItem:
    order_id: int
    number: str  # "{order_id}-{n}", ASSUMPTION: GAP-32
    beat: dict  # id, title, bpm, musical_key
    license_code: str
    license_name: str
    license_files: str
    price: Decimal
    fee: Decimal
    producer_id: int


def _party(data: dict) -> dict:
    name = " ".join(p for p in (data.get("last_name"), data.get("first_name"), data.get("middle_name")) if p)
    return {
        "name": name,
        "company": data.get("company_name"),
        "inn": data.get("inn"),
        "address": data.get("legal_address"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "display_name": data.get("display_name"),
        "id": data.get("user_id"),
    }


def render_draft(item: DraftItem, snapshot: dict, signature_type: str) -> str:
    terms = {**TERMS[item.license_code], "signature_clause": SIGNATURE_CLAUSE[signature_type]}
    return _env.get_template("contract.txt.j2").render(
        number=item.number,
        order_id=item.order_id,
        licensor=_party(snapshot["licensors"][str(item.producer_id)]),
        licensee=_party(snapshot["buyer"]),
        beat=item.beat,
        license={"name": item.license_name, "files": item.license_files},
        terms=terms,
        price=f"{item.price:.2f}",
        fee=f"{item.fee:.2f}",
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def license_files(includes_mp3: bool, includes_wav: bool, includes_stems: bool) -> str:
    parts = [n for flag, n in ((includes_mp3, "MP3 320 кбит/с"), (includes_wav, "WAV"), (includes_stems, "ZIP со стемами")) if flag]
    return ", ".join(parts)
