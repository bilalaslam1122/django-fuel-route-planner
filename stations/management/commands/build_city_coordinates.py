"""One-off: resolve every station city in the fuel CSV to coordinates.

The output (`data/city_coordinates.csv`) ships with the project, so this only
needs re-running when the fuel file gains new cities. It never runs per request.
"""

import tempfile
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from maps.exceptions import MapServiceError
from maps.geocoding import NominatimGeocoder
from stations.city_coordinates import (
    CityCoordinate,
    build_gazetteer_index,
    read_gazetteer,
    resolve_from_gazetteers,
    write_city_coordinates,
)
from stations.fuel_data import DatasetError, parse_fuel_csv
from stations.models import CoordinateSource

GAZETTEER_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer"
PLACES_FILE = "2024_Gaz_place_national.zip"
COUNTY_SUBDIVISIONS_FILE = "2024_Gaz_cousubs_national.zip"
NOMINATIM_MIN_INTERVAL_SECONDS = 1.1  # usage policy: at most 1 request/second


class Command(BaseCommand):
    help = "Build data/city_coordinates.csv from US Census Gazetteers (+ Nominatim fallback)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=Path, default=settings.FUEL_DATA_CSV)
        parser.add_argument("--output", type=Path, default=settings.CITY_COORDINATES_CSV)
        parser.add_argument(
            "--gazetteer-dir",
            type=Path,
            help="Directory holding the Census zip files (downloaded if absent).",
        )
        parser.add_argument(
            "--skip-nominatim", action="store_true", help="Leave Census misses unresolved."
        )

    def handle(self, *args, **options):
        try:
            with options["csv"].open(newline="", encoding="utf-8") as stream:
                parsed = parse_fuel_csv(stream)
        except (OSError, DatasetError) as exc:
            raise CommandError(f"Cannot read fuel data: {exc}") from exc
        cities = {(s.state, s.city) for s in parsed.stations.values()}
        self.stdout.write(f"{len(cities)} distinct US station cities")

        gazetteer_dir = options["gazetteer_dir"] or Path(tempfile.gettempdir()) / "census_gazetteer"
        places = build_gazetteer_index(read_gazetteer(self._fetch(gazetteer_dir, PLACES_FILE)))
        cousubs = build_gazetteer_index(
            read_gazetteer(self._fetch(gazetteer_dir, COUNTY_SUBDIVISIONS_FILE))
        )
        resolved, unresolved = resolve_from_gazetteers(cities, places, cousubs)
        self.stdout.write(f"Census Gazetteer resolved {len(resolved)}, missing {len(unresolved)}")

        if unresolved and not options["skip_nominatim"]:
            found, unresolved = self._resolve_with_nominatim(unresolved)
            resolved.extend(found)

        options["output"].parent.mkdir(parents=True, exist_ok=True)
        with options["output"].open("w", newline="", encoding="utf-8") as stream:
            write_city_coordinates(resolved, stream)

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(resolved)} cities to {options['output']}"))
        if unresolved:
            self.stdout.write(self.style.WARNING(f"{len(unresolved)} cities unresolved:"))
            for state, city in unresolved:
                self.stdout.write(f"  {city}, {state}")

    def _fetch(self, directory: Path, filename: str) -> Path:
        path = directory / filename
        if not path.exists():
            directory.mkdir(parents=True, exist_ok=True)
            self.stdout.write(f"Downloading {filename} ...")
            urllib.request.urlretrieve(f"{GAZETTEER_BASE}/{filename}", path)
        return path

    def _resolve_with_nominatim(self, cities):
        geocoder = NominatimGeocoder()
        found: list[CityCoordinate] = []
        missing: list[tuple[str, str]] = []
        self.stdout.write(f"Querying Nominatim for {len(cities)} cities (~1/s) ...")
        for state, city in cities:
            started = time.monotonic()
            try:
                place = geocoder.search_us_city(city, state)
            except MapServiceError as exc:
                self.stderr.write(f"  {city}, {state}: {exc}")
                place = None
            if place:
                found.append(
                    CityCoordinate(
                        state, city, place.latitude, place.longitude, CoordinateSource.NOMINATIM.value
                    )
                )
            else:
                missing.append((state, city))
            time.sleep(max(0.0, NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - started)))
        self.stdout.write(f"Nominatim resolved {len(found)}, missing {len(missing)}")
        return found, missing
