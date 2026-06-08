"""Currency and magnitude normalization to integer SEK (AC-4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from nlsearch.config import get_settings

_MAGNITUDE = {
    "k": 1_000,
    "tkr": 1_000,
    "t": 1_000,
    "m": 1_000_000,
    "miljon": 1_000_000,
    "million": 1_000_000,
    "milj": 1_000_000,
    "mkr": 1_000_000,
    "mdkr": 1_000_000_000,
    "bn": 1_000_000_000,
    "b": 1_000_000_000,
}

_CURRENCY_PATTERN = re.compile(
    r"(?:(?P<ccy_prefix>£|gbp|\$|usd|€|eur)\s*)?"
    r"(?P<amount>[\d.,]+)\s*(?P<mag>mkr|mdkr|miljon|million|milj|mkr|bn|tkr|k|m|b)?\s*"
    r"(?P<ccy>sek|kr|£|gbp|\$|usd|€|eur)?",
    re.I,
)

_RANGE_PATTERN = re.compile(
    r"(?P<lo>[\d.,]+)\s*[-–]\s*(?P<hi>[\d.,]+)\s*(?P<mag>mkr|mdkr|miljon|mkr|bn|k|m)?",
    re.I,
)


@dataclass
class MonetaryValue:
    amount_sek: int
    original: str
    converted_from: str | None = None


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", "").replace(" ", ""))


def _to_sek(amount: float, currency: str | None, magnitude: str | None) -> MonetaryValue:
    settings = get_settings()
    mult = _MAGNITUDE.get((magnitude or "").lower(), 1)
    base = amount * mult

    ccy = (currency or "sek").lower().replace("kr", "sek")
    converted_from = None
    if ccy in ("£", "gbp"):
        base *= settings.fx_gbp_to_sek
        converted_from = "GBP"
    elif ccy in ("$", "usd"):
        base *= settings.fx_usd_to_sek
        converted_from = "USD"
    elif ccy in ("€", "eur"):
        base *= settings.fx_eur_to_sek
        converted_from = "EUR"

    return MonetaryValue(int(base), f"{amount}{magnitude or ''}{currency or ''}", converted_from)


def parse_monetary_value(text: str) -> MonetaryValue | None:
    """Parse a single monetary mention from NL text."""
    # Ignore distances like "25km" / "100 km"
    if re.search(r"\d+\s*km\b", text, re.I) and not re.search(
        r"\d+\s*(mkr|mdkr|miljon|million|m|bn)\b", text, re.I
    ):
        return None
    m = _CURRENCY_PATTERN.search(text)
    if not m:
        return None
    raw_amount = m.group("amount")
    if not raw_amount or not any(c.isdigit() for c in raw_amount):
        return None
    try:
        amount = _parse_number(raw_amount)
    except ValueError:
        return None
    if not m.group("mag") and not m.group("ccy") and amount < 1000:
        # Avoid matching incidental numbers (e.g. "2024/0345")
        return None
    ccy = m.group("ccy") or m.group("ccy_prefix")
    return _to_sek(amount, ccy, m.group("mag"))


def parse_value_range(text: str) -> tuple[int, int] | None:
    """Parse '50–300M' style ranges."""
    m = _RANGE_PATTERN.search(text)
    if not m:
        return None
    lo = _parse_number(m.group("lo"))
    hi = _parse_number(m.group("hi"))
    mag = m.group("mag")
    mult = _MAGNITUDE.get((mag or "m").lower(), 1_000_000)
    return int(lo * mult), int(hi * mult)


def parse_comparison_threshold(text: str) -> tuple[str, int] | None:
    """Return ('>', amount) or ('BETWEEN', lo, hi) from phrases like 'over 100M'."""
    low = text.lower()
    between = parse_value_range(text)
    if between:
        return ("BETWEEN", between[0], between[1])  # type: ignore[return-value]

    mv = parse_monetary_value(text)
    if not mv:
        return None

    if re.search(r"\b(over|above|more than|över|större än|>)\b", low):
        return (">", mv.amount_sek)
    if re.search(r"\b(under|below|less than|under|<)\b", low):
        return ("<", mv.amount_sek)
    if re.search(r"\b(at least|min)\b", low):
        return (">=", mv.amount_sek)
    return (">", mv.amount_sek)
