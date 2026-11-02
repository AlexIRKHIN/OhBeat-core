"""Money (FR-15, FR-30, NFR-27). Only Decimal: float cannot hold 0.10 exactly."""

from decimal import ROUND_HALF_UP, Decimal

from app.common.config import get_settings

KOPECK = Decimal("0.01")


def service_fee(price: Decimal | int) -> Decimal:
    """The service fee is charged ON TOP of the Producer's price (FR-30); the percentage comes from
    the platform settings (GAP-10). ASSUMPTION: GAP-42 — per item, rounded half up to a kopeck."""
    percent = Decimal(get_settings().platform_fee_percent)
    return (Decimal(price) * percent / 100).quantize(KOPECK, rounding=ROUND_HALF_UP)


def rub(amount: Decimal) -> str:
    """Amount as YooKassa expects it: a string with two decimals, "4950.00"."""
    return f"{amount.quantize(KOPECK):.2f}"
