"""OSRM routing client: one request returns distance, duration and full geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from .exceptions import MapServiceError
from .http import get_json

LatLon = tuple[float, float]


class RouteNotFound(Exception):
    """The provider answered correctly but there is no drivable route."""


@dataclass(frozen=True)
class Route:
    distance_meters: float
    duration_seconds: float
    coordinates: list[LatLon]  # (lat, lon) along the road, start to finish


class OsrmRouter:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ROUTING_API_URL).rstrip("/")
        self.timeout = timeout or settings.EXTERNAL_API_TIMEOUT_SECONDS
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent or settings.EXTERNAL_API_USER_AGENT

    def route(self, start: LatLon, finish: LatLon) -> Route:
        waypoints = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in (start, finish))
        payload = get_json(
            self.session,
            f"{self.base_url}/route/v1/driving/{waypoints}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=self.timeout,
        )
        return _parse_route(payload)


def _parse_route(payload: Any) -> Route:
    if not isinstance(payload, dict):
        raise MapServiceError("Router returned an unexpected payload")
    code = payload.get("code")
    if code in {"NoRoute", "NoSegment"}:
        raise RouteNotFound(str(payload.get("message") or code))
    if code != "Ok" or not payload.get("routes"):
        raise MapServiceError(f"Router returned code {code!r}")

    route = payload["routes"][0]
    try:
        distance = float(route["distance"])
        duration = float(route["duration"])
        raw_coordinates = route["geometry"]["coordinates"]
        coordinates = [(float(lat), float(lon)) for lon, lat, *_ in raw_coordinates]
    except (KeyError, TypeError, ValueError) as exc:
        raise MapServiceError("Router returned a malformed route") from exc

    if len(coordinates) < 2 or not (math.isfinite(distance) and distance > 0 and duration >= 0):
        raise MapServiceError("Router returned an empty route")
    return Route(distance_meters=distance, duration_seconds=duration, coordinates=coordinates)
