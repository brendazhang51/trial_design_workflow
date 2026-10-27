"""Named deterministic normalizers; never add date precision or guess rounding."""

import calendar
import re
from decimal import Decimal, localcontext
from fractions import Fraction


class MappingException(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def clean_text(value: str) -> str:
    if any(
        ord(c) < 32
        and c not in "\n\r\t"
        or 0xD800 <= ord(c) <= 0xDFFF
        or ord(c) in {0xFFFE, 0xFFFF}
        for c in value
    ):
        raise MappingException("ILLEGAL_CHARACTER")
    if not value.strip():
        raise MappingException("EMPTY_VALUE")
    return value


def integer(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)", value):
        raise MappingException("INVALID_INTEGER")
    return str(int(value.replace(",", "")))


def decimal(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value):
        raise MappingException("INVALID_DECIMAL")
    return format(Decimal(value), "f")


def iso_date(value: str) -> str:
    value = value.strip()
    match = re.fullmatch(
        r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?"
        r"(?:T([0-9]{2})(?::([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?)?"
        r"(Z|[+-][0-9]{2}:[0-9]{2})?)?",
        value,
    )
    if not match:
        raise MappingException("INVALID_ISO8601_DATE")
    year, month, day, hour, minute, second, _, zone = match.groups()
    if int(year) == 0 or month and not 1 <= int(month) <= 12:
        raise MappingException("INVALID_ISO8601_DATE")
    if day and not 1 <= int(day) <= calendar.monthrange(int(year), int(month))[1]:
        raise MappingException("INVALID_ISO8601_DATE")
    if hour is not None and (
        day is None or int(hour) > 23 or minute and int(minute) > 59 or second and int(second) > 59
    ):
        raise MappingException("INVALID_ISO8601_DATE")
    if zone and zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:]) > 59):
        raise MappingException("INVALID_ISO8601_DATE")
    return value


def iso_duration(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"P[0-9]+(?:\.[0-9]+)?W", value):
        return value
    match = re.fullmatch(
        r"P(?:([0-9]+(?:\.[0-9]+)?)Y)?(?:([0-9]+(?:\.[0-9]+)?)M)?"
        r"(?:([0-9]+(?:\.[0-9]+)?)D)?(?:T(?:([0-9]+(?:\.[0-9]+)?)H)?"
        r"(?:([0-9]+(?:\.[0-9]+)?)M)?(?:([0-9]+(?:\.[0-9]+)?)S)?)?",
        value,
    )
    if not match or not any(match.groups()) or value.endswith("T"):
        raise MappingException("INVALID_ISO8601_DURATION")
    parts = [v for v in match.groups() if v is not None]
    if any("." in v for v in parts[:-1]):
        raise MappingException("INVALID_ISO8601_DURATION")
    return value


def ratio(numerator: str, denominator: str) -> str:
    n, d = int(integer(numerator)), int(integer(denominator))
    if d <= 0:
        raise MappingException("RATIO_DENOMINATOR_NOT_POSITIVE")
    if n > d:
        raise MappingException("RATIO_NUMERATOR_EXCEEDS_TOTAL")
    fraction = Fraction(n, d)
    reduced = fraction.denominator
    for prime in (2, 5):
        while reduced % prime == 0:
            reduced //= prime
    if reduced != 1:
        raise MappingException("RATIO_ROUNDING_POLICY_REQUIRED")
    with localcontext() as context:
        context.prec = len(str(n)) + len(str(d)) * 4 + 10
        result = format(Decimal(n) / Decimal(d), "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def split_tsval(value: str, *, limit=200) -> tuple[str, ...]:
    """IG 3.4 §7.4.2 Assumption 4 / §4.5.3.2: split between words, preserve text.

    Only called when the selected value profile explicitly enables that policy.
    A token without a legal word boundary remains a review exception.
    """
    parts = []
    while len(value) > limit:
        cut = max((i + 1 for i, c in enumerate(value[:limit]) if c.isspace()), default=0)
        if cut == 0:
            raise MappingException("LONG_TEXT_TOKEN_REQUIRES_REVIEW")
        parts.append(value[:cut])
        value = value[cut:]
    if value:
        parts.append(value)
    return tuple(parts)
