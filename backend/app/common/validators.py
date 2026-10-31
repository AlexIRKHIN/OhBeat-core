"""Field rules shared by several modules. Each function raises a PydanticCustomError
whose message is a key from app/common/i18n.py, so the error handler can translate it."""

import re

from pydantic_core import PydanticCustomError


def _fail(key: str, **params: object) -> PydanticCustomError:
    return PydanticCustomError("ohbeat", key, {"params": params})


# NFR-5: at least 8 characters, an uppercase Latin letter, a digit and a special character
_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def check_password(value: str) -> str:
    if (
        len(value) < 8
        or not re.search(r"[A-Z]", value)
        or not re.search(r"\d", value)
        or not _SPECIAL.search(value)
    ):
        raise _fail("password_weak")
    return value


def check_true(value: bool) -> bool:
    """Consents must be given explicitly (FR-31, FR-33)."""
    if value is not True:
        raise _fail("consent_required")
    return value


# UI spec §2 item 2: only letters, spaces and hyphens
_NAME = re.compile(r"^[A-Za-zА-Яа-яЁё]+(?:[ -][A-Za-zА-Яа-яЁё]+)*$")


def check_person_name(value: str) -> str:
    value = value.strip()
    if not _NAME.match(value):
        raise _fail("name_letters_only")
    return value


# E.164, the same pattern as CHECK billing_profiles_phone_check in schema.sql
_PHONE = re.compile(r"^\+[1-9][0-9]{6,14}$")


def check_phone(value: str) -> str:
    if not _PHONE.match(value):
        raise _fail("phone_invalid")
    return value


_INN_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _control_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights)) % 11 % 10


def is_valid_inn(inn: str) -> bool:
    """Checksum of a Russian INN: 10 digits for a company, 12 for a sole proprietor."""
    if not re.fullmatch(r"\d{10}|\d{12}", inn):
        return False
    d = [int(c) for c in inn]
    if len(d) == 10:
        return _control_digit(d, _INN_10) == d[9]
    return _control_digit(d, _INN_11) == d[10] and _control_digit(d, _INN_12) == d[11]


def check_inn(value: str) -> str:
    # The field is text, not a number: an INN may start with zero (UI spec §2 item 6)
    value = value.strip()
    if not re.fullmatch(r"\d{10}|\d{12}", value):
        raise _fail("inn_format")
    if not is_valid_inn(value):
        raise _fail("inn_checksum")
    return value


def fail(key: str, **params: object) -> PydanticCustomError:
    return _fail(key, **params)
