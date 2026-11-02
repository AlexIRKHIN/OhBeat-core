"""Messages of the API in Russian and English (NFR-26).

The language is taken from the Accept-Language header (ASSUMPTION: GAP-13); Russian is the default.
"""

from contextvars import ContextVar

DEFAULT_LOCALE = "ru"
_current_locale: ContextVar[str] = ContextVar("locale", default=DEFAULT_LOCALE)

MESSAGES: dict[str, dict[str, str]] = {
    "ru": {
        # Error codes (error_code -> message)
        "VALIDATION_ERROR": "Некорректные данные запроса",
        "AUTH_ERROR": "Требуется вход в систему",
        "FORBIDDEN": "Недостаточно прав",
        "NOT_FOUND": "Не найдено",
        "METHOD_NOT_ALLOWED": "Метод не поддерживается",
        "INTERNAL_ERROR": "Внутренняя ошибка сервера",
        "EMAIL_TAKEN": "Этот email уже зарегистрирован",
        "INVALID_CREDENTIALS": "Неверный email или пароль",
        "TOO_MANY_ATTEMPTS": "Слишком много неудачных попыток входа. Попробуйте через 15 минут",
        "INVALID_REFRESH_TOKEN": "Сессия истекла, войдите снова",
        "ALREADY_PRODUCER": "Вы уже подключены к продажам",
        "BILLING_REQUIRED": "Сначала заполните данные для договора",
        "STORAGE_UNAVAILABLE": "Хранилище файлов временно недоступно, попробуйте позже",
        "INVALID_STATUS": "Действие недоступно в текущем статусе бита",
        "FILES_MISSING": "Не все файлы загружены в хранилище",
        "BEAT_SOLD": "Эксклюзивные права на этот бит уже проданы",
        "BEAT_RESERVED": "Этот эксклюзив прямо сейчас оформляет другой покупатель",
        "LAST_ACTIVE_LICENSE": "У бита должна остаться хотя бы одна активная лицензия",
        "STEMS_REQUIRED": "Лицензии Trackout и Exclusive требуют ZIP со стемами",
        # Field issues (details[].issue)
        "required": "Обязательное поле",
        "invalid_value": "Недопустимое значение",
        "invalid_type": "Неверный тип значения",
        "too_short": "Слишком короткое значение: минимум {min} символов",
        "too_long": "Слишком длинное значение: максимум {max} символов",
        "invalid_email": "Некорректный email",
        "password_weak": "Пароль: не менее 8 символов, заглавная латинская буква, цифра и спецсимвол",
        "consent_required": "Нужно ваше согласие",
        "name_letters_only": "Допускаются только буквы, пробелы и дефисы",
        "phone_invalid": "Телефон в международном формате, например +79001234567",
        "inn_format": "ИНН: 10 цифр для организации или 12 цифр для ИП",
        "inn_checksum": "Неверная контрольная сумма ИНН",
        "business_field_required": "Обязательно для ИП и юридических лиц",
        "file_type_not_allowed": "Допустимы только JPG, PNG или WebP",
        "file_too_large": "Файл больше {max_mb} МБ",
        "file_not_uploaded": "Файл не найден в хранилище, загрузите его заново",
        "image_invalid": "Файл не является изображением JPG, PNG или WebP",
        "image_too_big": "Разрешение изображения больше 2048×2048 px",
        "extension_mismatch": "Расширение файла не соответствует его типу",
        "duplicate_values": "Значения не должны повторяться",
        "forbidden_word": "Запрещенное слово",
        "unknown_genre": "Такого жанра нет в справочнике",
        "stems_required": "Нужен для Trackout и Exclusive",
        "file_extension_not_allowed": "Недопустимое расширение файла",
        "file_type_not_allowed_for": "Недопустимый тип файла",
        "file_not_declared": "Этот файл не заявлен при создании бита",
    },
    "en": {
        "VALIDATION_ERROR": "Invalid request data",
        "AUTH_ERROR": "Sign-in required",
        "FORBIDDEN": "Not enough permissions",
        "NOT_FOUND": "Not found",
        "METHOD_NOT_ALLOWED": "Method not allowed",
        "INTERNAL_ERROR": "Internal server error",
        "EMAIL_TAKEN": "This email is already registered",
        "INVALID_CREDENTIALS": "Wrong email or password",
        "TOO_MANY_ATTEMPTS": "Too many failed sign-in attempts. Try again in 15 minutes",
        "INVALID_REFRESH_TOKEN": "Session expired, please sign in again",
        "ALREADY_PRODUCER": "You are already connected to sales",
        "BILLING_REQUIRED": "Fill in your contract details first",
        "STORAGE_UNAVAILABLE": "File storage is temporarily unavailable, try again later",
        "INVALID_STATUS": "This action is not available in the current status of the beat",
        "FILES_MISSING": "Not all files are uploaded to storage",
        "BEAT_SOLD": "Exclusive rights to this beat are already sold",
        "BEAT_RESERVED": "Another buyer is checking out this exclusive right now",
        "LAST_ACTIVE_LICENSE": "A beat must keep at least one active license",
        "STEMS_REQUIRED": "Trackout and Exclusive licenses require a ZIP with stems",
        "required": "Required field",
        "invalid_value": "Invalid value",
        "invalid_type": "Invalid value type",
        "too_short": "Too short: at least {min} characters",
        "too_long": "Too long: at most {max} characters",
        "invalid_email": "Invalid email",
        "password_weak": "Password: at least 8 characters, an uppercase Latin letter, a digit and a special character",
        "consent_required": "Your consent is required",
        "name_letters_only": "Only letters, spaces and hyphens are allowed",
        "phone_invalid": "Phone in international format, e.g. +79001234567",
        "inn_format": "INN: 10 digits for a company or 12 digits for a sole proprietor",
        "inn_checksum": "Invalid INN checksum",
        "business_field_required": "Required for sole proprietors and companies",
        "file_type_not_allowed": "Only JPG, PNG or WebP are allowed",
        "file_too_large": "File is larger than {max_mb} MB",
        "file_not_uploaded": "File not found in storage, upload it again",
        "image_invalid": "File is not a JPG, PNG or WebP image",
        "image_too_big": "Image resolution is larger than 2048×2048 px",
        "extension_mismatch": "File extension does not match its type",
        "duplicate_values": "Values must not repeat",
        "forbidden_word": "Forbidden word",
        "unknown_genre": "No such genre in the dictionary",
        "stems_required": "Required for Trackout and Exclusive",
        "file_extension_not_allowed": "File extension is not allowed",
        "file_type_not_allowed_for": "File type is not allowed",
        "file_not_declared": "This file was not declared when the beat was created",
    },
}


def locale_from_header(accept_language: str | None) -> str:
    if accept_language and accept_language.strip().lower().startswith("en"):
        return "en"
    return DEFAULT_LOCALE


def set_locale(locale: str) -> None:
    _current_locale.set(locale)


def t(key: str, **params: object) -> str:
    """Translate a message key into the language of the current request."""
    template = MESSAGES[_current_locale.get()].get(key) or MESSAGES[DEFAULT_LOCALE].get(key, key)
    return template.format(**params) if params else template
