from decimal import Decimal

from app.core.enums import AmountPrecision, DurationPrecision


def format_duration(seconds: int | None, precision: str | None = None) -> str | None:
    if seconds is None:
        return None
    minutes = round(seconds / 60)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        text = f"{hours}h {rest:02d}m"
    elif hours:
        text = f"{hours}h"
    else:
        text = f"{rest}m"
    if precision == DurationPrecision.APPROXIMATE:
        text = f"~{text}"
    return text


def format_amount(
    amount: Decimal | None, currency: str | None, precision: str | None = None
) -> str | None:
    if amount is None:
        return None
    text = str(int(amount)) if amount == amount.to_integral_value() else f"{amount:.2f}"
    if currency:
        text = f"{text} {currency}"
    if precision == AmountPrecision.APPROXIMATE:
        text = f"~{text}"
    return text
