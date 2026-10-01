import io
from decimal import Decimal

from django.test import SimpleTestCase

from stations.fuel_data import DatasetError, parse_fuel_csv

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"


def parse(*rows: str):
    return parse_fuel_csv(io.StringIO(HEADER + "".join(f"{r}\n" for r in rows)))


class ParseFuelCsvTests(SimpleTestCase):
    def test_valid_row_is_normalized(self):
        result = parse('7,WOODSHED OF BIG CABIN,"I-44, EXIT 283 & US-69",Big Cabin   ,ok,307,3.00733333')

        station = result.stations[7]
        self.assertEqual(station.name, "WOODSHED OF BIG CABIN")
        self.assertEqual(station.address, "I-44, EXIT 283 & US-69")
        self.assertEqual(station.city, "Big Cabin")
        self.assertEqual(station.state, "OK")
        self.assertEqual(station.rack_id, 307)
        self.assertEqual(station.price_per_gallon, Decimal("3.00733"))
        self.assertEqual(result.invalid_rows, [])

    def test_duplicate_station_keeps_lowest_price(self):
        result = parse(
            "105,TA SAGINAW,I-75 EXIT 144,Bridgeport,MI,260,3.339",
            "105,TA SAGINAW,I-75 EXIT 144,Bridgeport,MI,260,3.269",
            "105,TA SAGINAW,I-75 EXIT 144,Bridgeport,MI,260,3.429",
        )

        self.assertEqual(len(result.stations), 1)
        self.assertEqual(result.stations[105].price_per_gallon, Decimal("3.269"))
        self.assertEqual(result.duplicate_rows, 2)
        self.assertEqual(result.conflicting_price_ids, {105})

    def test_exact_duplicate_is_merged_without_conflict(self):
        result = parse("20,PILOT #1243,I-8,Gila Bend,AZ,930,3.899", "20,PILOT #1243,I-8,Gila Bend,AZ,930,3.899")

        self.assertEqual(result.duplicate_rows, 1)
        self.assertEqual(result.conflicting_price_ids, set())

    def test_missing_price_is_reported_as_invalid(self):
        result = parse("1,A,I-1,Austin,TX,1,", "2,B,I-1,Austin,TX,1,3.10")

        self.assertEqual(list(result.stations), [2])
        self.assertEqual(len(result.invalid_rows), 1)
        self.assertEqual(result.invalid_rows[0].line, 2)
        self.assertIn("missing Retail Price", result.invalid_rows[0].reason)

    def test_non_numeric_zero_and_absurd_prices_are_invalid(self):
        result = parse("1,A,I-1,Austin,TX,1,abc", "2,A,I-1,Austin,TX,1,0", "3,A,I-1,Austin,TX,1,99", "4,A,I-1,Austin,TX,1,NaN")

        self.assertEqual(result.stations, {})
        self.assertEqual(len(result.invalid_rows), 4)

    def test_invalid_identifier_state_and_missing_fields_are_invalid(self):
        result = parse(
            "abc,A,I-1,Austin,TX,1,3.0",
            "5,A,I-1,Austin,ZZ,1,3.0",
            "6,,I-1,Austin,TX,1,3.0",
            "7,A,I-1,,TX,1,3.0",
        )

        reasons = [issue.reason for issue in result.invalid_rows]
        self.assertEqual(len(reasons), 4)
        self.assertIn("invalid OPIS Truckstop ID", reasons[0])
        self.assertIn("unknown state code", reasons[1])
        self.assertIn("missing Truckstop Name", reasons[2])
        self.assertIn("missing City", reasons[3])

    def test_canadian_rows_are_skipped_not_invalid(self):
        result = parse("67027,FLYING J #806,HWY 11,Kapuskasing,ON,460,5.30", "8,A,I-1,Austin,TX,1,3.0")

        self.assertEqual(result.non_us_rows, 1)
        self.assertEqual(result.invalid_rows, [])
        self.assertEqual(list(result.stations), [8])

    def test_blank_rack_id_is_allowed(self):
        self.assertIsNone(parse("1,A,I-1,Austin,TX,,3.0").stations[1].rack_id)

    def test_missing_column_is_a_dataset_error(self):
        with self.assertRaisesMessage(DatasetError, "Retail Price"):
            parse_fuel_csv(io.StringIO("OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID\n1,A,B,C,TX,1\n"))

    def test_file_without_rows_is_a_dataset_error(self):
        with self.assertRaises(DatasetError):
            parse_fuel_csv(io.StringIO(HEADER))
