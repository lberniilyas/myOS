import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

KNOWN_CURRENCIES = frozenset(
    {
        "AED",
        "AUD",
        "BHD",
        "BRL",
        "CAD",
        "CHF",
        "CNY",
        "CZK",
        "DKK",
        "DZD",
        "EGP",
        "EUR",
        "GBP",
        "HKD",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "JOD",
        "JPY",
        "KES",
        "KRW",
        "KWD",
        "LBP",
        "MAD",
        "MXN",
        "MYR",
        "NGN",
        "NOK",
        "NZD",
        "OMR",
        "PHP",
        "PKR",
        "PLN",
        "QAR",
        "RON",
        "RUB",
        "SAR",
        "SEK",
        "SGD",
        "THB",
        "TND",
        "TRY",
        "UAH",
        "USD",
        "VND",
        "XAF",
        "XOF",
        "ZAR",
    }
)

MAX_AMOUNT = Decimal("1000000000")
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_DECIMAL_COMMA = re.compile(r"^\d+,\d{1,2}$")
CENT = Decimal("0.01")


def parse_amount(value: object) -> Decimal | None:
    """Parse a positive money amount, or return None when it isn't a clean number."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "")
    if _THOUSANDS.match(text):
        text = text.replace(",", "")
    elif _DECIMAL_COMMA.match(text):
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount >= MAX_AMOUNT:
        return None
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_currency(code: object) -> str | None:
    if not isinstance(code, str):
        return None
    upper = code.strip().upper()
    return upper if upper in KNOWN_CURRENCIES else None
