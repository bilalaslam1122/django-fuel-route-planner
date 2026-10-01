from unittest import mock

import requests
from django.test import SimpleTestCase

from maps.exceptions import MapServiceError, MapServiceTimeout
from maps.routing import OsrmRouter, RouteNotFound


def fake_session(payload=None, status=200, exc=None) -> mock.Mock:
    session = mock.Mock(spec=requests.Session)
    session.headers = {}
    if exc:
        session.get.side_effect = exc
    else:
        session.get.return_value = mock.Mock(status_code=status, json=mock.Mock(return_value=payload))
    return session


OK = {
    "code": "Ok",
    "routes": [
        {
            "distance": 313619.8,
            "duration": 12443.5,
            "geometry": {"type": "LineString", "coordinates": [[-97.74, 30.27], [-97.0, 31.5], [-96.8, 32.78]]},
        }
    ],
}


class OsrmRouterTests(SimpleTestCase):
    def router(self, session):
        return OsrmRouter("https://osrm.example/", user_agent="test", timeout=4, session=session)

    def test_parses_route_and_requests_full_geojson_in_lon_lat_order(self):
        session = fake_session(OK)

        route = self.router(session).route((30.27, -97.74), (32.78, -96.8))

        self.assertEqual(route.distance_meters, 313619.8)
        self.assertEqual(route.duration_seconds, 12443.5)
        self.assertEqual(route.coordinates[0], (30.27, -97.74))  # converted to (lat, lon)
        url = session.get.call_args.args[0]
        self.assertEqual(url, "https://osrm.example/route/v1/driving/-97.740000,30.270000;-96.800000,32.780000")
        self.assertEqual(session.get.call_args.kwargs["params"]["overview"], "full")
        self.assertEqual(session.get.call_args.kwargs["timeout"], 4)

    def test_no_route_is_a_distinct_error(self):
        with self.assertRaises(RouteNotFound):
            self.router(fake_session({"code": "NoRoute", "message": "Impossible route"})).route((0, 0), (1, 1))

    def test_provider_error_codes_and_malformed_payloads_raise_service_error(self):
        bad_payloads = [
            {"code": "InvalidQuery"},
            {"code": "Ok", "routes": []},
            {"code": "Ok", "routes": [{"distance": 1, "duration": 1}]},
            {"code": "Ok", "routes": [{"distance": 1, "duration": 1, "geometry": {"coordinates": [[1, 2]]}}]},
            ["not", "a", "dict"],
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload), self.assertRaises(MapServiceError):
                self.router(fake_session(payload)).route((0, 0), (1, 1))

    def test_timeout_and_http_errors(self):
        with self.assertRaises(MapServiceTimeout):
            self.router(fake_session(exc=requests.Timeout())).route((0, 0), (1, 1))
        with self.assertRaises(MapServiceError):
            self.router(fake_session(status=500)).route((0, 0), (1, 1))
