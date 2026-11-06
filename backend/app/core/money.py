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
# French/Moroccan writing: "1.200" is twelve hundred, "1.200,50" twelve hundred and a half.
# Three digits after a dot never mean cents, so this can't swallow "12.50".
_DOT_THOUSANDS = re.compile(r"^[1-9]\d{0,2}(\.\d{3})+(,\d{1,2})?$")
_DECIMAL_COMMA = re.compile(r"^\d+,\d{1,2}$")
_PLAIN = re.compile(r"^\d+(\.\d+)?$")
_SPACES = re.compile(r"[\s  ]")
CENT = Decimal("0.01")


def parse_amount(value: object) -> Decimal | None:
    """Parse a positive money amount, or return None when it isn't a clean number."""
    if value is None or isinstance(value, bool):
        return None
    text = _SPACES.sub("", str(value))
    if _THOUSANDS.match(text):
        text = text.replace(",", "")
    elif _DOT_THOUSANDS.match(text):
        text = text.replace(".", "").replace(",", ".")
    elif _DECIMAL_COMMA.match(text):
        text = text.replace(",", ".")
    if not _PLAIN.match(text):  # no signs, exponents ("1e3") or words
        return None
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
