"""API tests. Geocoder and router are replaced with fakes: no real HTTP calls."""

from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from maps.exceptions import MapServiceError, MapServiceTimeout
from maps.geocoding import GeocodedPlace
from maps.routing import Route, RouteNotFound
from stations.models import FuelStation
from trips import station_index

# A straight road along latitude 40 from lon -100 to -88: about 636 road miles.
WEST = GeocodedPlace(40.0, -100.0, "West Town, Kansas, United States", "us", "KS")
EAST = GeocodedPlace(40.0, -88.0, "East City, Illinois, United States", "us", "IL")
TORONTO = GeocodedPlace(43.65, -79.38, "Toronto, Ontario, Canada", "ca", None)
TORONTO_IA = GeocodedPlace(41.86, -90.86, "Toronto, Clinton County, Iowa, United States", "us", "IA")
SAN_JUAN = GeocodedPlace(18.47, -66.1, "San Juan, Puerto Rico, United States", "us", "PR")
ROUTE = Route(
    distance_meters=636 * 1609.344,
    duration_seconds=9 * 3600,
    coordinates=[(40.0, -100.0 + i * 0.05) for i in range(241)],
)


class FakeGeocoder:
    places = {
        "west town, ks": [WEST],
        "east city, il": [EAST],
        "toronto": [TORONTO, TORONTO_IA],
        "san juan, pr": [SAN_JUAN],
    }

    def __init__(self):
        self.calls = 0

    def search(self, query, limit=5):
        self.calls += 1
        return self.places.get(query.lower(), [])


class FakeRouter:
    def __init__(self, result=ROUTE):
        self.result = result
        self.calls = 0

    def route(self, start, finish):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def add_station(opis_id, lon, price, lat=40.0):
    return FuelStation.objects.create(
        opis_id=opis_id, name=f"STATION {opis_id}", address="I-70", city=f"Town {opis_id}", state="KS",
        price_per_gallon=Decimal(price), latitude=lat, longitude=lon, coordinate_source="census_place",
    )


class RouteApiTests(TestCase):
    url = "/api/route/"

    def setUp(self):
        cache.clear()
        station_index._cached = None
        self.geocoder, self.router = FakeGeocoder(), FakeRouter()
        patches = [
            mock.patch("trips.planner.NominatimGeocoder", return_value=self.geocoder),
            mock.patch("trips.planner.OsrmRouter", side_effect=lambda: self.router),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        add_station(1, -95.0, "3.50")  # ~265 miles from the start
        add_station(2, -93.0, "3.00")  # ~371 miles, cheaper
        add_station(3, -94.0, "1.00", lat=41.0)  # cheap but ~69 miles off the route

    def post(self, body, path=None, **kwargs):
        return self.client.post(path or self.url, body, content_type="application/json", **kwargs)

    def test_valid_request_returns_route_and_cheapest_fuel_plan(self):
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["start"]["state"], "KS")
        self.assertEqual(body["route"]["distance_miles"], 636.0)
        self.assertEqual(body["route"]["duration_minutes"], 540)
        self.assertEqual(body["route"]["geometry"]["type"], "LineString")
        self.assertEqual(body["vehicle"]["tank_capacity_gallons"], 50)

        plan = body["fuel_plan"]
        self.assertEqual([s["station_id"] for s in plan["stops"]], [2])  # cheaper, not nearer or off-route
        stop = plan["stops"][0]
        self.assertAlmostEqual(stop["distance_from_start_miles"], 371, delta=3)
        self.assertEqual(stop["fuel_price_per_gallon"], 3.0)
        self.assertAlmostEqual(stop["gallons_purchased"], (636 - 500) / 10, delta=0.01)
        self.assertEqual(Decimal(str(stop["cost"])), Decimal(str(stop["gallons_purchased"])) * 3)
        self.assertEqual(plan["total_cost"], stop["cost"])
        self.assertEqual(plan["fuel_used_gallons"], 63.6)
        self.assertEqual(body["meta"]["candidate_stations"], 2)
        self.assertEqual(body["meta"]["external_api_calls"], 3)

    def test_trailing_slash_is_optional(self):
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"}, path="/api/route")
        self.assertEqual(response.status_code, 200)

    def test_repeat_request_is_served_from_cache(self):
        self.post({"start": "West Town, KS", "finish": "East City, IL"})
        body = self.post({"start": "west town,  KS", "finish": "East City, IL"}).json()

        self.assertEqual(body["meta"]["external_api_calls"], 0)
        self.assertEqual((self.geocoder.calls, self.router.calls), (2, 1))

    def test_geometry_can_be_omitted(self):
        body = self.post({"start": "West Town, KS", "finish": "East City, IL", "include_geometry": False}).json()
        self.assertNotIn("geometry", body["route"])

    def test_missing_start(self):
        response = self.post({"finish": "East City, IL"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertIn("start", response.json()["error"]["details"])

    def test_missing_finish(self):
        response = self.post({"start": "West Town, KS"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("finish", response.json()["error"]["details"])

    def test_blank_location_is_rejected(self):
        self.assertEqual(self.post({"start": "   ", "finish": "East City, IL"}).status_code, 400)

    def test_invalid_json(self):
        response = self.post('{"start": "West Town, KS",')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "malformed_json")

    def test_get_is_not_allowed(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_unknown_location(self):
        response = self.post({"start": "Qwertyuiop", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "location_not_found")
        self.assertEqual(response.json()["error"]["details"]["field"], "start")

    def test_non_usa_location_is_rejected_with_us_suggestions(self):
        response = self.post({"start": "Toronto", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "location_outside_usa")
        self.assertIn("Canada", error["message"])
        self.assertEqual(error["details"]["did_you_mean"], [TORONTO_IA.display_name])
        self.assertEqual(self.router.calls, 0)

    def test_us_territory_is_rejected(self):
        response = self.post({"start": "West Town, KS", "finish": "San Juan, PR"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("US territory", response.json()["error"]["message"])

    def test_same_start_and_finish(self):
        response = self.post({"start": "West Town, KS", "finish": "west town, ks"})
        self.assertEqual(response.json()["error"]["code"], "same_location")

    def test_route_api_failure(self):
        self.router.result = MapServiceError("HTTP 503 from provider internals")
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "map_service_unavailable")
        self.assertNotIn("internals", response.json()["error"]["message"])  # provider detail not leaked

    def test_route_api_timeout(self):
        self.router.result = MapServiceTimeout("slow")
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"]["code"], "map_service_timeout")

    def test_no_drivable_route(self):
        self.router.result = RouteNotFound("NoRoute")
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "route_not_found")

    def test_no_feasible_fuel_plan(self):
        FuelStation.objects.filter(opis_id__in=[1, 2]).delete()
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "no_feasible_fuel_plan")
        self.assertEqual(error["details"]["stranded_after_miles"], 0)

    def test_fuel_data_not_loaded(self):
        FuelStation.objects.all().delete()
        response = self.post({"start": "West Town, KS", "finish": "East City, IL"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "fuel_data_unavailable")

    def test_stations_without_coordinates_are_ignored(self):
        FuelStation.objects.filter(opis_id=2).update(latitude=None, longitude=None)
        body = self.post({"start": "West Town, KS", "finish": "East City, IL"}).json()

        self.assertEqual([s["station_id"] for s in body["fuel_plan"]["stops"]], [1])
