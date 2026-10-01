"""Nominatim (OpenStreetMap) geocoding client."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from .exceptions import MapServiceError
from .http import get_json


@dataclass(frozen=True)
class GeocodedPlace:
    latitude: float
    longitude: float
    display_name: str
    country_code: str  # ISO 3166-1 alpha-2, lower case ("us", "ca", ...)
    state_code: str | None  # "TX" for US results when Nominatim reports it


class NominatimGeocoder:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or settings.GEOCODING_API_URL).rstrip("/")
        self.timeout = timeout or settings.EXTERNAL_API_TIMEOUT_SECONDS
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent or settings.EXTERNAL_API_USER_AGENT

    def search(self, query: str, *, limit: int = 5) -> list[GeocodedPlace]:
        """Free-text search, worldwide, best match first."""
        return self._search({"q": query, "limit": limit})

    def search_us_city(self, city: str, state_code: str) -> GeocodedPlace | None:
        """Structured city lookup, accepted only if Nominatim agrees on the state."""
        results = self._search({"city": city, "state": state_code, "country": "us", "limit": 3})
        return next((r for r in results if r.state_code == state_code), None)

    def _search(self, params: dict[str, Any]) -> list[GeocodedPlace]:
        payload = get_json(
            self.session,
            f"{self.base_url}/search",
            params={**params, "format": "jsonv2", "addressdetails": 1},
            timeout=self.timeout,
        )
        if not isinstance(payload, list):
            raise MapServiceError("Geocoder returned an unexpected payload")
        return [place for item in payload if (place := _parse_place(item)) is not None]


def _parse_place(item: Any) -> GeocodedPlace | None:
    """Parse one result, skipping (rather than trusting) malformed entries."""
    if not isinstance(item, dict):
        return None
    try:
        lat, lon = float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    iso_region = str(address.get("ISO3166-2-lvl4", ""))
    return GeocodedPlace(
        latitude=lat,
        longitude=lon,
        display_name=str(item.get("display_name", "")),
        country_code=str(address.get("country_code", "")).lower(),
        state_code=iso_region[3:] if iso_region.startswith("US-") else None,
    )
