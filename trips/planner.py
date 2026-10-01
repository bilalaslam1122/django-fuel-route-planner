"""Orchestrates a trip plan: geocode -> route -> match stations -> optimize -> response.

External calls per request: at most 2 geocodes + 1 route, each cached, so a
repeated trip makes none. Station matching and optimization are local.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from maps.exceptions import MapServiceError, MapServiceTimeout
from maps.geocoding import GeocodedPlace, NominatimGeocoder
from maps.routing import OsrmRouter, Route
from maps.routing import RouteNotFound as ProviderRouteNotFound
from stations.geo import US_STATE_CODES, haversine_miles

from . import exceptions as errors
from .geometry import RouteLine
from .optimizer import FuelCandidate, NoFeasiblePlan, Vehicle, cost_of, plan_fuel_stops, round_gallons
from .station_index import get_station_index

METERS_PER_MILE = 1609.344
MIN_TRIP_MILES = 1.0


@dataclass
class _CallStats:
    external_calls: int = 0
    cache_hits: int = 0
    timings_ms: dict[str, float] = field(default_factory=dict)


class TripPlanner:
    def __init__(
        self,
        geocoder: NominatimGeocoder | None = None,
        router: OsrmRouter | None = None,
        vehicle: Vehicle | None = None,
        corridor_miles: float | None = None,
    ) -> None:
        self.geocoder = geocoder or NominatimGeocoder()
        self.router = router or OsrmRouter()
        self.vehicle = vehicle or Vehicle(settings.VEHICLE_MAX_RANGE_MILES, settings.VEHICLE_MPG)
        self.corridor_miles = corridor_miles or settings.ROUTE_CORRIDOR_MILES

    def plan(self, start_query: str, finish_query: str, include_geometry: bool = True) -> dict:
        stats = _CallStats()
        started = time.perf_counter()

        start = self._resolve("start", start_query, stats)
        finish = self._resolve("finish", finish_query, stats)
        if haversine_miles(start.latitude, start.longitude, finish.latitude, finish.longitude) < MIN_TRIP_MILES:
            raise errors.SameLocation("Start and finish resolve to the same place.")

        route = self._route(start, finish, stats)
        total_miles = route.distance_meters / METERS_PER_MILE

        t0 = time.perf_counter()
        line = RouteLine.from_coordinates(route.coordinates, total_miles, settings.ROUTE_SAMPLING_MILES)
        candidates, stations_by_id, offsets = self._candidates(line)
        stats.timings_ms["station_matching"] = _ms_since(t0)

        t0 = time.perf_counter()
        try:
            fuel_plan = plan_fuel_stops(total_miles, candidates, self.vehicle)
        except NoFeasiblePlan as exc:
            raise errors.NoFeasibleFuelPlan(
                "No fuel plan can reach the destination: the route has a stretch longer than "
                f"{self.vehicle.max_range_miles:.0f} miles without a known fuel station.",
                {
                    "stranded_after_miles": round(exc.stranded_at_miles, 1),
                    "gap_miles": round(exc.gap_miles, 1) if exc.gap_miles is not None else None,
                    "candidate_stations": len(candidates),
                },
            ) from exc
        stats.timings_ms["optimization"] = _ms_since(t0)
        stats.timings_ms["total"] = _ms_since(started)

        return self._response(
            start_query, start, finish_query, finish, route, line, fuel_plan,
            stations_by_id, offsets, len(candidates), stats, include_geometry,
        )

    # --- external calls (cached) -------------------------------------------

    def _resolve(self, field_name: str, query: str, stats: _CallStats) -> GeocodedPlace:
        key = "geocode:" + hashlib.sha256(" ".join(query.lower().split()).encode()).hexdigest()
        places = cache.get(key)
        if places is None:
            places = self._call(lambda: self.geocoder.search(query, limit=5), stats, "geocoding")
            cache.set(key, places, settings.GEOCODE_CACHE_SECONDS)
        else:
            stats.cache_hits += 1

        if not places:
            raise errors.LocationNotFound(
                f"Could not find {field_name} location {query!r}.", {"field": field_name}
            )
        best = places[0]  # trust the geocoder's ranking; never silently switch countries
        if best.country_code == "us" and best.state_code in US_STATE_CODES:
            return best

        us_alternatives = [p.display_name for p in places if p.state_code in US_STATE_CODES]
        where = "a US territory" if best.country_code == "us" else "outside the USA"
        raise errors.LocationOutsideUSA(
            f"{field_name.capitalize()} location {query!r} resolved to {best.display_name}, which is {where}. "
            "Both locations must be in the 50 states or DC.",
            {"field": field_name, "did_you_mean": us_alternatives[:3]} if us_alternatives else {"field": field_name},
        )

    def _route(self, start: GeocodedPlace, finish: GeocodedPlace, stats: _CallStats) -> Route:
        key = "route:{:.5f},{:.5f};{:.5f},{:.5f}".format(
            start.latitude, start.longitude, finish.latitude, finish.longitude
        )
        route = cache.get(key)
        if route is not None:
            stats.cache_hits += 1
            return route
        try:
            route = self._call(
                lambda: self.router.route((start.latitude, start.longitude), (finish.latitude, finish.longitude)),
                stats,
                "routing",
            )
        except ProviderRouteNotFound as exc:
            raise errors.RouteNotFound("No drivable route exists between these locations.") from exc
        cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
        return route

    @staticmethod
    def _call(fn, stats: _CallStats, service: str):
        stats.external_calls += 1
        t0 = time.perf_counter()
        try:
            return fn()
        except MapServiceTimeout as exc:
            raise errors.MapServiceTimedOut(f"The {service} service timed out. Please retry.") from exc
        except MapServiceError as exc:
            raise errors.MapServiceUnavailable(f"The {service} service is unavailable. Please retry.") from exc
        finally:
            stats.timings_ms[service] = stats.timings_ms.get(service, 0) + _ms_since(t0)

    # --- local work --------------------------------------------------------

    def _candidates(self, line: RouteLine):
        index = get_station_index()
        if not index.stations:
            raise errors.FuelDataUnavailable(
                "No fuel stations are loaded. Run `python manage.py import_fuel_data`."
            )
        nearby = index.within_box(line.bounding_box(self.corridor_miles))
        offsets, along = line.project(index.lat[nearby], index.lon[nearby])
        inside = offsets <= self.corridor_miles

        candidates, stations_by_id, offset_by_id = [], {}, {}
        for i, offset, position in zip(nearby[inside], offsets[inside], along[inside]):
            station = index.stations[int(i)]
            candidates.append(FuelCandidate(station.opis_id, float(position), station.price_per_gallon))
            stations_by_id[station.opis_id] = station
            offset_by_id[station.opis_id] = float(offset)
        return candidates, stations_by_id, offset_by_id

    def _response(
        self, start_query, start, finish_query, finish, route, line, fuel_plan,
        stations_by_id, offsets, candidate_count, stats, include_geometry,
    ) -> dict:
        stops = []
        total_cost = Decimal("0.00")
        total_gallons = Decimal("0.000")
        for number, stop in enumerate(fuel_plan.stops, start=1):
            station = stations_by_id[stop.candidate.station_id]
            cost = cost_of(stop.gallons_purchased, station.price_per_gallon)
            gallons = round_gallons(stop.gallons_purchased)
            total_cost += cost
            total_gallons += gallons
            stops.append({
                "stop_number": number,
                "station_id": station.opis_id,
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "distance_from_start_miles": round(stop.candidate.position_miles, 1),
                "distance_from_route_miles": round(offsets[station.opis_id], 1),
                "fuel_price_per_gallon": station.price_per_gallon.quantize(Decimal("0.001")),
                "fuel_on_arrival_gallons": float(round_gallons(stop.fuel_on_arrival_gallons)),
                "gallons_purchased": float(gallons),
                "cost": cost,
            })

        route_body = {
            "distance_miles": round(route.distance_meters / METERS_PER_MILE, 1),
            "duration_minutes": round(route.duration_seconds / 60),
        }
        if include_geometry:
            route_body["geometry"] = line.geojson()

        return {
            "start": _place(start_query, start),
            "finish": _place(finish_query, finish),
            "route": route_body,
            "vehicle": {
                "max_range_miles": self.vehicle.max_range_miles,
                "fuel_economy_mpg": self.vehicle.miles_per_gallon,
                "tank_capacity_gallons": self.vehicle.tank_capacity_gallons,
                "starting_fuel_gallons": self.vehicle.tank_capacity_gallons,
            },
            "fuel_plan": {
                "currency": "USD",
                "number_of_stops": len(stops),
                "total_gallons_purchased": float(total_gallons),
                "total_cost": total_cost,
                "fuel_used_gallons": float(round_gallons(fuel_plan.fuel_used_gallons)),
                "fuel_remaining_at_finish_gallons": float(round_gallons(fuel_plan.fuel_at_finish_gallons)),
                "cost_basis": "total_cost is the money spent at fuel stops; the trip starts with a full tank.",
                "stops": stops,
            },
            "meta": {
                "route_corridor_miles": self.corridor_miles,
                "candidate_stations": candidate_count,
                "external_api_calls": stats.external_calls,
                "cache_hits": stats.cache_hits,
                "timings_ms": {k: round(v, 1) for k, v in stats.timings_ms.items()},
            },
        }


def _place(query: str, place: GeocodedPlace) -> dict:
    return {
        "query": query,
        "resolved_name": place.display_name,
        "state": place.state_code,
        "latitude": place.latitude,
        "longitude": place.longitude,
    }


def _ms_since(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000
