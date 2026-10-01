"""City-level coordinates for fuel stations.

The supplied fuel file has no latitude/longitude, only highway/exit addresses
(e.g. "I-44, EXIT 283 & US-69") which free geocoders cannot resolve reliably.
Stations are therefore located by their city/state, resolved offline:

1. US Census Gazetteer "places" (incorporated cities, towns, CDPs).
2. US Census Gazetteer "county subdivisions" (townships etc.).
3. Nominatim, rate-limited, only for the few names the Census files miss.

The result is written once to `data/city_coordinates.csv`, which ships with
the project, so neither setup nor API requests ever geocode stations.
"""

from __future__ import annotations

import csv
import io
import re
import statistics
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from .geo import haversine_miles
from .models import CoordinateSource

CityKey = tuple[str, str]  # (state code, normalized city name)

# Places sharing a name inside one state are only merged if they are this
# close; otherwise the name is ambiguous and falls through to the next source.
MAX_DUPLICATE_SPREAD_MILES = 15.0

_ABBREVIATIONS = {"ST": "SAINT", "STE": "SAINTE", "FT": "FORT", "MT": "MOUNT", "PT": "POINT"}

# Gazetteer names end with a legal/statistical area descriptor ("Abbeville city",
# "Abanda CDP"). Longest patterns first so compound descriptors win.
_GAZETTEER_SUFFIX = re.compile(
    r"\s+("
    r"(city and borough|unified government|metropolitan government|metro government|"
    r"consolidated government|urban county)( \(balance\))?"
    r"|city \(balance\)|\(balance\)"
    r"|city|town|village|borough|township|cdp|ccd|municipality|plantation|gore|grant|"
    r"location|purchase|unorganized territory|ut|precinct|district|comunidad|zona urbana"
    r")$",
    re.IGNORECASE,
)


def normalize_city(name: str) -> str:
    """Canonical matching key: "Mc Calla" == "McCalla", "E St. Louis" == "E Saint Louis",
    "Cañon City" == "Canon City". Spaces are dropped entirely for that reason."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[.',]", "", text.upper()).replace("-", " ")
    return "".join(_ABBREVIATIONS.get(word, word) for word in text.split())


def strip_gazetteer_suffix(name: str) -> str:
    return _GAZETTEER_SUFFIX.sub("", name.strip())


@dataclass(frozen=True)
class CityCoordinate:
    state: str
    city: str
    latitude: float
    longitude: float
    source: str


def build_gazetteer_index(rows: Iterable[dict[str, str]]) -> dict[CityKey, tuple[float, float]]:
    """Map (state, city) -> point, dropping names that are ambiguous within a state."""
    points: dict[CityKey, list[tuple[float, float]]] = defaultdict(list)
    # Consolidated city-counties ("Macon-Bibb County", "Lexington-Fayette") are
    # also reachable by their leading city name, unless a real place has it.
    aliases: dict[CityKey, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        try:
            lat, lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
        except (KeyError, ValueError):
            continue
        state = row["USPS"].strip()
        name = strip_gazetteer_suffix(row["NAME"])
        points[(state, normalize_city(name))].append((lat, lon))
        if "-" in name:
            aliases[(state, normalize_city(name.split("-")[0]))].append((lat, lon))

    index: dict[CityKey, tuple[float, float]] = {}
    for source in (aliases, points):  # real names overwrite aliases
        for key, pts in source.items():
            merged = _merge_if_close(pts)
            if merged:
                index[key] = merged
            elif source is points:
                index.pop(key, None)
    return index


def _merge_if_close(pts: list[tuple[float, float]]) -> tuple[float, float] | None:
    lat = statistics.fmean(p[0] for p in pts)
    lon = statistics.fmean(p[1] for p in pts)
    if all(haversine_miles(lat, lon, p[0], p[1]) <= MAX_DUPLICATE_SPREAD_MILES for p in pts):
        return lat, lon
    return None


def read_gazetteer(path: Path) -> list[dict[str, str]]:
    """Read a Census Gazetteer file (tab-separated, optionally zipped)."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            member = next(n for n in archive.namelist() if n.endswith(".txt"))
            text = archive.read(member).decode("utf-8", errors="replace")
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    # The last header carries trailing whitespace in the Census files.
    return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]


def resolve_from_gazetteers(
    cities: Iterable[tuple[str, str]],
    place_index: dict[CityKey, tuple[float, float]],
    cousub_index: dict[CityKey, tuple[float, float]],
) -> tuple[list[CityCoordinate], list[tuple[str, str]]]:
    """Resolve (state, city) pairs; returns (resolved, unresolved)."""
    resolved: list[CityCoordinate] = []
    unresolved: list[tuple[str, str]] = []
    for state, city in sorted(set(cities)):
        key = (state, normalize_city(city))
        for index, source in (
            (place_index, CoordinateSource.CENSUS_PLACE),
            (cousub_index, CoordinateSource.CENSUS_COUNTY_SUBDIVISION),
        ):
            if key in index:
                lat, lon = index[key]
                resolved.append(CityCoordinate(state, city, lat, lon, source.value))
                break
        else:
            unresolved.append((state, city))
    return resolved, unresolved


CSV_FIELDS = ["state", "city", "latitude", "longitude", "source"]


def write_city_coordinates(coordinates: Iterable[CityCoordinate], stream: TextIO) -> None:
    writer = csv.writer(stream)
    writer.writerow(CSV_FIELDS)
    for c in sorted(coordinates, key=lambda c: (c.state, c.city)):
        writer.writerow([c.state, c.city, f"{c.latitude:.6f}", f"{c.longitude:.6f}", c.source])


def load_city_coordinates(path: Path) -> dict[CityKey, CityCoordinate]:
    """Load the pre-built lookup, keyed by (state, normalized city)."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(f"{path} must have columns {CSV_FIELDS}, got {reader.fieldnames}")
        lookup: dict[CityKey, CityCoordinate] = {}
        for row in reader:
            coordinate = CityCoordinate(
                state=row["state"],
                city=row["city"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                source=row["source"],
            )
            lookup[(coordinate.state, normalize_city(coordinate.city))] = coordinate
        return lookup
