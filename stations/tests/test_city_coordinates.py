import io
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from stations.city_coordinates import (
    CityCoordinate,
    build_gazetteer_index,
    load_city_coordinates,
    normalize_city,
    resolve_from_gazetteers,
    strip_gazetteer_suffix,
    write_city_coordinates,
)


def gaz(state: str, name: str, lat: float, lon: float) -> dict[str, str]:
    return {"USPS": state, "NAME": name, "INTPTLAT": str(lat), "INTPTLONG": str(lon)}


class NormalizationTests(SimpleTestCase):
    def test_spelling_variants_share_a_key(self):
        pairs = [
            ("Mc Calla", "McCalla"),
            ("La Salle", "LaSalle"),
            ("East Saint Louis", "East St. Louis"),
            ("Sault Sainte Marie", "Sault Ste. Marie"),
            ("Canon City", "Cañon City"),
            ("Fort Worth", "Ft Worth"),
        ]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertEqual(normalize_city(a), normalize_city(b))

    def test_gazetteer_suffix_is_stripped_once(self):
        self.assertEqual(strip_gazetteer_suffix("Abbeville city"), "Abbeville")
        self.assertEqual(strip_gazetteer_suffix("Junction City city"), "Junction City")
        self.assertEqual(strip_gazetteer_suffix("Abanda CDP"), "Abanda")
        self.assertEqual(
            strip_gazetteer_suffix("Macon-Bibb County unified government (balance)"), "Macon-Bibb County"
        )


class GazetteerIndexTests(SimpleTestCase):
    def test_ambiguous_far_apart_names_are_dropped(self):
        index = build_gazetteer_index(
            [gaz("TX", "Springfield city", 30.0, -97.0), gaz("TX", "Springfield CDP", 33.0, -101.0)]
        )
        self.assertNotIn(("TX", normalize_city("Springfield")), index)

    def test_nearby_duplicates_are_merged(self):
        index = build_gazetteer_index([gaz("TX", "Foo city", 30.0, -97.0), gaz("TX", "Foo CDP", 30.02, -97.0)])
        lat, _ = index[("TX", "FOO")]
        self.assertAlmostEqual(lat, 30.01)

    def test_consolidated_city_alias(self):
        index = build_gazetteer_index([gaz("GA", "Macon-Bibb County unified government (balance)", 32.8, -83.7)])
        self.assertEqual(index[("GA", "MACON")], (32.8, -83.7))

    def test_places_take_precedence_over_county_subdivisions(self):
        places = {("TX", "AUSTIN"): (30.3, -97.7)}
        cousubs = {("TX", "AUSTIN"): (0.0, 0.0), ("TX", "ELMO"): (32.7, -96.2)}

        resolved, unresolved = resolve_from_gazetteers(
            [("TX", "Austin"), ("TX", "Elmo"), ("TX", "Nowhere")], places, cousubs
        )

        by_city = {c.city: c for c in resolved}
        self.assertEqual(by_city["Austin"].source, "census_place")
        self.assertEqual(by_city["Elmo"].source, "census_cousub")
        self.assertEqual(unresolved, [("TX", "Nowhere")])


class CoordinateFileTests(SimpleTestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coords.csv"
            with path.open("w", newline="") as stream:
                write_city_coordinates([CityCoordinate("IL", "La Salle", 41.33, -89.09, "census_place")], stream)

            lookup = load_city_coordinates(path)

        self.assertEqual(lookup[("IL", "LASALLE")].latitude, 41.33)

    def test_wrong_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coords.csv"
            path.write_text("city,lat\nAustin,30\n")
            with self.assertRaises(ValueError):
                load_city_coordinates(path)

    def test_write_is_sorted_and_stable(self):
        stream = io.StringIO()
        write_city_coordinates(
            [CityCoordinate("TX", "Waco", 31.5, -97.1, "x"), CityCoordinate("AL", "Mobile", 30.7, -88.0, "x")], stream
        )
        self.assertEqual(stream.getvalue().splitlines()[1].split(",")[0], "AL")
