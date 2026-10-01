import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from stations.city_coordinates import CityCoordinate
from stations.fuel_data import StationRecord
from stations.importer import sync_stations
from stations.models import FuelStation

COORDS = {("TX", "AUSTIN"): CityCoordinate("TX", "Austin", 30.27, -97.74, "census_place")}


def record(opis_id: int, price: str = "3.10", city: str = "Austin") -> StationRecord:
    return StationRecord(opis_id, f"STATION {opis_id}", "I-35", city, "TX", 1, Decimal(price))


class SyncStationsTests(TestCase):
    def test_creates_stations_with_coordinates(self):
        result = sync_stations([record(1)], COORDS)

        station = FuelStation.objects.get(opis_id=1)
        self.assertEqual(result.created, 1)
        self.assertEqual((station.latitude, station.longitude), (30.27, -97.74))
        self.assertEqual(station.coordinate_source, "census_place")
        self.assertTrue(station.has_coordinates)

    def test_station_without_known_city_is_stored_without_coordinates(self):
        result = sync_stations([record(2, city="Atlantis")], COORDS)

        station = FuelStation.objects.get(opis_id=2)
        self.assertFalse(station.has_coordinates)
        self.assertEqual([r.opis_id for r in result.without_coordinates], [2])

    def test_rerun_is_idempotent(self):
        sync_stations([record(1), record(2)], COORDS)
        result = sync_stations([record(1), record(2)], COORDS)

        self.assertEqual((result.created, result.updated, result.deleted), (0, 2, 0))
        self.assertEqual(FuelStation.objects.count(), 2)

    def test_rerun_updates_prices_and_removes_stale_stations(self):
        sync_stations([record(1, "3.10"), record(2)], COORDS)
        result = sync_stations([record(1, "2.95")], COORDS)

        self.assertEqual(result.deleted, 1)
        self.assertEqual(FuelStation.objects.get().price_per_gallon, Decimal("2.95"))


class ImportCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "coords.csv").write_text(
            "state,city,latitude,longitude,source\nTX,Austin,30.27,-97.74,census_place\n"
        )
        (self.dir / "fuel.csv").write_text(
            "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
            "1,A,I-35,Austin,TX,1,3.20\n"
            "1,A,I-35,Austin,TX,1,3.10\n"
            "2,B,HWY 11,Kapuskasing,ON,1,5.30\n"
            "3,C,I-35,Austin,TX,1,\n"
        )

    def run_import(self) -> str:
        out = StringIO()
        call_command(
            "import_fuel_data", csv=self.dir / "fuel.csv", coordinates=self.dir / "coords.csv", stdout=out
        )
        return out.getvalue()

    def test_reports_counts_and_imports(self):
        output = self.run_import()

        self.assertIn("Skipped (Canada):          1", output)
        self.assertIn("Invalid rows:              1", output)
        self.assertIn("Duplicate rows merged:     1", output)
        self.assertEqual(FuelStation.objects.get().price_per_gallon, Decimal("3.10"))

    def test_running_twice_gives_same_result(self):
        self.run_import()
        output = self.run_import()

        self.assertIn("created / updated / deleted: 0 / 1 / 0", output)
        self.assertEqual(FuelStation.objects.count(), 1)

    def test_missing_file_is_a_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_fuel_data", csv=self.dir / "nope.csv", stdout=StringIO())

    def test_missing_coordinates_file_explains_how_to_build_it(self):
        with self.assertRaisesMessage(CommandError, "build_city_coordinates"):
            call_command(
                "import_fuel_data", csv=self.dir / "fuel.csv", coordinates=self.dir / "nope.csv", stdout=StringIO()
            )
