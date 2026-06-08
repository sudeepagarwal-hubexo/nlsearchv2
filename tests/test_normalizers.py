"""AC-4 normalization fixtures."""

import pytest
from datetime import datetime

import pytz

from nlsearch.normalizers.currency import parse_monetary_value, parse_value_range
from nlsearch.normalizers.dates import parse_relative_date_range
from nlsearch.normalizers.places import PlaceResolver
from nlsearch.vocabulary.synonyms import normalize_role_from_text, normalize_stage


@pytest.mark.parametrize(
    "text,expected_sek",
    [
        ("100M", 100_000_000),
        ("100 million", 100_000_000),
        ("100mkr", 100_000_000),
        ("1 mdkr", 1_000_000_000),
        ("500k", 500_000),
        ("50 tkr", 50_000),
    ],
)
def test_currency_magnitudes(text: str, expected_sek: int) -> None:
    mv = parse_monetary_value(text)
    assert mv is not None
    assert mv.amount_sek == expected_sek


def test_currency_range() -> None:
    r = parse_value_range("50–300M")
    assert r == (50_000_000, 300_000_000)


def test_relative_dates_next_year() -> None:
    ref = datetime(2026, 6, 1, tzinfo=pytz.timezone("Europe/Stockholm"))
    dr = parse_relative_date_range("starting next year", reference=ref)
    assert dr is not None
    assert dr.field_hint == "construction_start_date"
    assert dr.start.year == 2027


@pytest.mark.parametrize(
    "phrase,role",
    [
        ("byggherre on the project", "Client"),
        ("main contractor", "MainContractor"),
        ("huvudentreprenör", "MainContractor"),
        ("project manager", "ProjectManager"),
    ],
)
def test_role_synonyms(phrase: str, role: str) -> None:
    assert normalize_role_from_text(phrase) == role


@pytest.mark.parametrize(
    "token,stage",
    [
        ("upphandling", "Tender"),
        ("byggstart", "Construction"),
        ("tender", "Tender"),
    ],
)
def test_stage_synonyms(token: str, stage: str) -> None:
    assert normalize_stage(token) == stage


def test_place_resolver_solna() -> None:
    p = PlaceResolver().resolve("Projects in Solna")
    assert p is not None
    assert p.value == "Solna"
