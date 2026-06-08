"""Relative date resolution against Europe/Stockholm (AC-4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from nlsearch.config import get_settings


@dataclass
class DateRange:
    start: datetime
    end: datetime
    field_hint: str
    assumption: str | None = None


def _now() -> datetime:
    tz = pytz.timezone(get_settings().timezone)
    return datetime.now(tz)


def _bind_field(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(complet|finish|end)\b", low):
        return "construction_end_date"
    if re.search(r"\b(new|updated|since)\b", low):
        return "last_modified_at"
    if re.search(r"\b(start|ground|breaking|begin)\b", low):
        return "construction_start_date"
    return "construction_start_date"


def parse_relative_date_range(text: str, reference: datetime | None = None) -> DateRange | None:
    now = reference or _now()
    low = text.lower()
    field = _bind_field(text)
    assumption = None

    if "next year" in low:
        y = now.year + 1
        return DateRange(
            datetime(now.year + 1, 1, 1, tzinfo=now.tzinfo).replace(year=y),
            datetime(y, 12, 31, 23, 59, 59, tzinfo=now.tzinfo),
            field,
        )

    if m := re.search(r"next\s+(\d+)\s+months?", low):
        months = int(m.group(1))
        return DateRange(now, now + relativedelta(months=months), field)

    if re.search(r"this week|last 7 days|past week", low):
        return DateRange(now - timedelta(days=7), now, "last_modified_at")

    if re.search(r"since last week|last week", low):
        return DateRange(now - timedelta(days=7), now, "last_modified_at")

    if re.search(r"last\s+30\s+days|past\s+30\s+days|updated in the last 30", low):
        return DateRange(now - timedelta(days=30), now, "last_modified_at")

    if re.search(r"6 months|half a year", low) and ("not updated" in low or "stale" in low):
        return DateRange(datetime(1970, 1, 1, tzinfo=now.tzinfo), now - timedelta(days=180), "last_modified_at")

    if re.search(r"breaking ground", low) and re.search(r"(\d+)\s*months?", low):
        m = re.search(r"(\d+)\s*months?", low)
        if m:
            days = int(m.group(1)) * 30
            return DateRange(now, now + timedelta(days=days), "construction_start_date")

    if re.search(r"today", low) and re.search(r"\d+\s*months?", low):
        m = re.search(r"(\d+)\s*months?", low)
        if m:
            days = int(m.group(1)) * 30
            return DateRange(now, now + timedelta(days=days), field)

    if re.search(r"what'?s new|since last week", low):
        return DateRange(now - timedelta(days=7), now, "last_modified_at")

    if re.search(r"starting next year", low):
        y = now.year + 1
        return DateRange(
            datetime(y, 1, 1, tzinfo=now.tzinfo),
            datetime(y, 12, 31, 23, 59, 59, tzinfo=now.tzinfo),
            field,
        )

    if field == "construction_start_date" and not re.search(
        r"\b(start|ground|complet|updated|since)\b", low
    ):
        assumption = "Ambiguous temporal phrase bound to construction_start_date"

    return None
