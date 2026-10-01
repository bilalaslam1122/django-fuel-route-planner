"""Parse and validate the supplied OPIS fuel-price CSV (no database access)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TextIO

from .geo import US_STATE_CODES

COLUMN_ID = "OPIS Truckstop ID"
COLUMN_NAME = "Truckstop Name"
COLUMN_ADDRESS = "Address"
COLUMN_CITY = "City"
COLUMN_STATE = "State"
COLUMN_RACK = "Rack ID"
COLUMN_PRICE = "Retail Price"
REQUIRED_COLUMNS = (
    COLUMN_ID, COLUMN_NAME, COLUMN_ADDRESS, COLUMN_CITY, COLUMN_STATE, COLUMN_RACK, COLUMN_PRICE
)

# The file also lists Canadian truck stops (priced in CAD); they are skipped
# because trips are USA-only.
CANADIAN_PROVINCE_CODES = frozenset("AB BC MB NB NL NS NT NU ON PE QC SK YT".split())

PRICE_PRECISION = Decimal("0.00001")
MAX_PLAUSIBLE_PRICE = Decimal("20")


class DatasetError(Exception):
    """The file as a whole is unusable (unreadable, wrong columns, empty)."""


@dataclass(frozen=True)
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int | None
    price_per_gallon: Decimal


@dataclass(frozen=True)
class RowIssue:
    line: int
    reason: str


@dataclass
class ParseResult:
    stations: dict[int, StationRecord] = field(default_factory=dict)
    total_rows: int = 0
    non_us_rows: int = 0
    duplicate_rows: int = 0
    conflicting_price_ids: set[int] = field(default_factory=set)
    invalid_rows: list[RowIssue] = field(default_factory=list)


class InvalidRow(ValueError):
    pass


def parse_fuel_csv(stream: TextIO) -> ParseResult:
    """Validate, normalize and deduplicate the fuel file.

    Duplicate rows for one OPIS id keep the lowest price: a driver stopping
    there would use the cheapest pump the dataset reports.
    """
    reader = csv.DictReader(stream)
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise DatasetError(f"Missing required column(s): {', '.join(missing)}")
    reader.fieldnames = header

    result = ParseResult()
    for row in reader:
        result.total_rows += 1
        state = _clean(row.get(COLUMN_STATE)).upper()
        if state in CANADIAN_PROVINCE_CODES:
            result.non_us_rows += 1
            continue
        try:
            record = _parse_row(row, state)
        except InvalidRow as exc:
            result.invalid_rows.append(RowIssue(reader.line_num, str(exc)))
            continue

        existing = result.stations.get(record.opis_id)
        if existing is None:
            result.stations[record.opis_id] = record
            continue
        result.duplicate_rows += 1
        if existing.price_per_gallon != record.price_per_gallon:
            result.conflicting_price_ids.add(record.opis_id)
        if record.price_per_gallon < existing.price_per_gallon:
            result.stations[record.opis_id] = record

    if result.total_rows == 0:
        raise DatasetError("The fuel file contains no data rows")
    return result


def _parse_row(row: dict[str, str | None], state: str) -> StationRecord:
    opis_id = _parse_positive_int(row.get(COLUMN_ID))
    if opis_id is None:
        raise InvalidRow(f"invalid {COLUMN_ID} {row.get(COLUMN_ID)!r}")
    if state not in US_STATE_CODES:
        raise InvalidRow(f"unknown state code {state!r}")

    name, city = _clean(row.get(COLUMN_NAME)), _clean(row.get(COLUMN_CITY))
    if not name:
        raise InvalidRow(f"missing {COLUMN_NAME}")
    if not city:
        raise InvalidRow(f"missing {COLUMN_CITY}")

    return StationRecord(
        opis_id=opis_id,
        name=name,
        address=_clean(row.get(COLUMN_ADDRESS)),
        city=city,
        state=state,
        rack_id=_parse_positive_int(row.get(COLUMN_RACK)),
        price_per_gallon=_parse_price(row.get(COLUMN_PRICE)),
    )


def _clean(value: str | None) -> str:
    """Trim and collapse internal whitespace (City values are space-padded)."""
    return " ".join((value or "").split())


def _parse_positive_int(value: str | None) -> int | None:
    try:
        number = int(_clean(value))
    except ValueError:
        return None
    return number if number > 0 else None


def _parse_price(value: str | None) -> Decimal:
    raw = _clean(value)
    if not raw:
        raise InvalidRow(f"missing {COLUMN_PRICE}")
    try:
        price = Decimal(raw)
    except InvalidOperation:
        raise InvalidRow(f"non-numeric {COLUMN_PRICE} {raw!r}") from None
    if not price.is_finite() or not (0 < price <= MAX_PLAUSIBLE_PRICE):
        raise InvalidRow(f"implausible {COLUMN_PRICE} {raw!r}")
    return price.quantize(PRICE_PRECISION)
