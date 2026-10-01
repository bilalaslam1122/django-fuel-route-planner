from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stations.city_coordinates import load_city_coordinates
from stations.fuel_data import DatasetError, parse_fuel_csv
from stations.importer import sync_stations

MAX_ISSUES_SHOWN = 20


class Command(BaseCommand):
    help = "Import the fuel-price CSV into FuelStation (idempotent; safe to re-run)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=Path, default=settings.FUEL_DATA_CSV)
        parser.add_argument("--coordinates", type=Path, default=settings.CITY_COORDINATES_CSV)

    def handle(self, *args, **options):
        try:
            with options["csv"].open(newline="", encoding="utf-8") as stream:
                parsed = parse_fuel_csv(stream)
        except (OSError, UnicodeDecodeError, DatasetError) as exc:
            raise CommandError(f"Cannot import {options['csv']}: {exc}") from exc
        try:
            coordinates = load_city_coordinates(options["coordinates"])
        except (OSError, ValueError) as exc:
            raise CommandError(
                f"Cannot read {options['coordinates']}: {exc}. "
                "Run `python manage.py build_city_coordinates` to create it."
            ) from exc

        synced = sync_stations(parsed.stations.values(), coordinates)

        out = self.stdout.write
        out(f"Rows read:                 {parsed.total_rows}")
        out(f"Skipped (Canada):          {parsed.non_us_rows}")
        out(f"Invalid rows:              {len(parsed.invalid_rows)}")
        out(f"Duplicate rows merged:     {parsed.duplicate_rows} "
            f"({len(parsed.conflicting_price_ids)} stations had differing prices; lowest kept)")
        out(f"Unique US stations:        {len(parsed.stations)}")
        out(f"  created / updated / deleted: {synced.created} / {synced.updated} / {synced.deleted}")
        out(f"  without coordinates:     {len(synced.without_coordinates)} (excluded from routing)")

        for issue in parsed.invalid_rows[:MAX_ISSUES_SHOWN]:
            self.stdout.write(self.style.WARNING(f"  line {issue.line}: {issue.reason}"))
        for record in synced.without_coordinates[:MAX_ISSUES_SHOWN]:
            self.stdout.write(
                self.style.WARNING(f"  no coordinates: #{record.opis_id} {record.city}, {record.state}")
            )
        self.stdout.write(self.style.SUCCESS("Fuel data import complete."))
