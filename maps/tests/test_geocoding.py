from unittest import mock

import requests
from django.test import SimpleTestCase

from maps.exceptions import MapServiceError, MapServiceTimeout
from maps.geocoding import NominatimGeocoder


def fake_session(payload=None, status=200, exc=None, json_error=False) -> mock.Mock:
    session = mock.Mock(spec=requests.Session)
    session.headers = {}
    if exc:
        session.get.side_effect = exc
    else:
        response = mock.Mock(status_code=status)
        response.json.side_effect = ValueError("bad json") if json_error else None
        response.json.return_value = payload
        session.get.return_value = response
    return session


def place(lat="30.2672", lon="-97.7431", country="us", region="US-TX", name="Austin, Texas, United States"):
    return {
        "lat": lat,
        "lon": lon,
        "display_name": name,
        "address": {"country_code": country, "ISO3166-2-lvl4": region},
    }


class NominatimGeocoderTests(SimpleTestCase):
    def geocoder(self, session):
        return NominatimGeocoder("https://geo.example/", user_agent="test-agent", timeout=3, session=session)

    def test_search_parses_results_and_sends_identifying_request(self):
        session = fake_session([place()])

        results = self.geocoder(session).search("Austin, TX")

        self.assertEqual(len(results), 1)
        self.assertEqual((results[0].latitude, results[0].longitude), (30.2672, -97.7431))
        self.assertEqual((results[0].country_code, results[0].state_code), ("us", "TX"))
        url = session.get.call_args.args[0]
        kwargs = session.get.call_args.kwargs
        self.assertEqual(url, "https://geo.example/search")
        self.assertEqual(kwargs["timeout"], 3)
        self.assertEqual(kwargs["params"]["q"], "Austin, TX")
        self.assertEqual(session.headers["User-Agent"], "test-agent")

    def test_non_us_result_has_no_state_code(self):
        results = self.geocoder(fake_session([place(country="ca", region="CA-ON")])).search("Toronto")
        self.assertEqual((results[0].country_code, results[0].state_code), ("ca", None))

    def test_malformed_entries_are_skipped(self):
        session = fake_session([{"lat": "x", "lon": "1"}, "junk", place(lat="95"), place()])
        self.assertEqual(len(self.geocoder(session).search("Austin")), 1)

    def test_structured_city_search_requires_matching_state(self):
        session = fake_session([place(region="US-OK"), place(region="US-TX", lat="31")])

        result = self.geocoder(session).search_us_city("Paris", "TX")

        self.assertEqual(result.latitude, 31.0)
        self.assertEqual(session.get.call_args.kwargs["params"]["country"], "us")

    def test_structured_city_search_returns_none_without_match(self):
        self.assertIsNone(self.geocoder(fake_session([place(region="US-OK")])).search_us_city("Paris", "TX"))

    def test_timeout_raises_timeout_error(self):
        with self.assertRaises(MapServiceTimeout):
            self.geocoder(fake_session(exc=requests.Timeout())).search("Austin")

    def test_connection_error_raises_service_error(self):
        with self.assertRaises(MapServiceError):
            self.geocoder(fake_session(exc=requests.ConnectionError())).search("Austin")

    def test_http_error_raises_service_error(self):
        with self.assertRaisesMessage(MapServiceError, "HTTP 503"):
            self.geocoder(fake_session(status=503)).search("Austin")

    def test_non_json_and_unexpected_payloads_raise_service_error(self):
        with self.assertRaises(MapServiceError):
            self.geocoder(fake_session(json_error=True)).search("Austin")
        with self.assertRaises(MapServiceError):
            self.geocoder(fake_session({"error": "nope"})).search("Austin")
