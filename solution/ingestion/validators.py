
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalize_header(header):
    """Normalize CSV headers for schema matching."""
    header = header.strip().lower()
    return re.sub(r"[_\s]+", " ", header)


def normalize_phone(value):
    """Convert an Indian phone number into canonical +91 format."""
    if value is None:
        return None

    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("invalid_phone")

    return "+91" + digits


def parse_date(value):
    """Parse supported day-first and ISO date formats."""
    if value is None or str(value).strip() == "":
        return None

    value = str(value).strip()

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
    ]

    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue

    raise ValueError("invalid_date")


def parse_decimal(value):
    """Parse non-negative premium amounts and round to 2 decimals."""
    if value is None or str(value).strip() == "":
        return None

    amount = str(value).strip()

    amount = re.sub(
        r"^(₹|Rs\.?|INR)\s*",
        "",
        amount,
        flags=re.IGNORECASE
    )

    amount = amount.replace(",", "")

    try:
        number = Decimal(amount)
    except InvalidOperation:
        raise ValueError("invalid_decimal")

    if not number.is_finite() or number < 0:
        raise ValueError("invalid_decimal")

    return str(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_enum(value, allowed_values):
    """Validate enum values without case sensitivity."""
    if value is None or str(value).strip() == "":
        return None

    normalized = str(value).strip().lower()

    allowed = [item.lower() for item in allowed_values]

    if normalized not in allowed:
        raise ValueError("invalid_enum")

    return normalized


def validate_string(value):
    """Trim a string value."""
    if value is None:
        return None

    return str(value).strip()
