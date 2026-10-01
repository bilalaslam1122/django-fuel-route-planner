"""Route geometry: thinning, cumulative distance and station-to-route projection.

All of this is local maths on the single route returned by the routing API;
no external calls are made per station.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from stations.geo import EARTH_RADIUS_MILES

MILES_PER_DEGREE = EARTH_RADIUS_MILES * np.pi / 180
STATION_CHUNK = 256  # bounds memory: chunk x segments matrices


def haversine_path_miles(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Length of each consecutive segment of a lat/lon polyline."""
    phi = np.radians(lat)
    dphi = np.diff(phi)
    dlambda = np.radians(np.diff(lon))
    a = np.sin(dphi / 2) ** 2 + np.cos(phi[:-1]) * np.cos(phi[1:]) * np.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


@dataclass(frozen=True)
class RouteLine:
    lat: np.ndarray
    lon: np.ndarray
    cumulative_miles: np.ndarray  # road miles from the start at each vertex

    @classmethod
    def from_coordinates(
        cls, coordinates: list[tuple[float, float]], road_distance_miles: float, spacing_miles: float
    ) -> "RouteLine":
        """Thin the provider geometry to roughly one vertex per `spacing_miles`.

        Cumulative distances are rescaled so the last vertex equals the provider's
        road distance, keeping station positions consistent with it.
        """
        points = np.asarray(coordinates, dtype=float)
        lat, lon = points[:, 0], points[:, 1]
        cumulative = np.concatenate([[0.0], np.cumsum(haversine_path_miles(lat, lon))])

        bucket = np.floor(cumulative / spacing_miles)
        keep = np.concatenate([[True], np.diff(bucket) > 0])
        keep[-1] = True
        lat, lon, cumulative = lat[keep], lon[keep], cumulative[keep]

        if cumulative[-1] > 0:
            cumulative = cumulative * (road_distance_miles / cumulative[-1])
        return cls(lat=lat, lon=lon, cumulative_miles=cumulative)

    def geojson(self) -> dict:
        return {
            "type": "LineString",
            "coordinates": [[round(x, 5), round(y, 5)] for x, y in zip(self.lon.tolist(), self.lat.tolist())],
        }

    def bounding_box(self, margin_miles: float) -> tuple[float, float, float, float]:
        lat_margin = margin_miles / MILES_PER_DEGREE
        widest = np.cos(np.radians(np.max(np.abs(self.lat))))
        lon_margin = margin_miles / (MILES_PER_DEGREE * max(widest, 0.1))
        return (
            float(self.lat.min() - lat_margin),
            float(self.lat.max() + lat_margin),
            float(self.lon.min() - lon_margin),
            float(self.lon.max() + lon_margin),
        )

    def project(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """For each point return (miles off the route, road miles from start of its
        closest point on the route).

        Each segment uses its own equirectangular scale (longitude shrinks with
        latitude), which is accurate to well under a mile at segment length.
        """
        a_lat, b_lat = self.lat[:-1], self.lat[1:]
        a_lon, b_lon = self.lon[:-1], self.lon[1:]
        x_scale = MILES_PER_DEGREE * np.cos(np.radians((a_lat + b_lat) / 2))
        dx = (b_lon - a_lon) * x_scale
        dy = (b_lat - a_lat) * MILES_PER_DEGREE
        length_sq = np.where(dx * dx + dy * dy > 0, dx * dx + dy * dy, 1.0)
        segment_miles = np.diff(self.cumulative_miles)

        offsets = np.empty(len(lat))
        along = np.empty(len(lat))
        for start in range(0, len(lat), STATION_CHUNK):
            chunk = slice(start, start + STATION_CHUNK)
            px = (lon[chunk, None] - a_lon[None, :]) * x_scale
            py = (lat[chunk, None] - a_lat[None, :]) * MILES_PER_DEGREE
            t = np.clip((px * dx + py * dy) / length_sq, 0.0, 1.0)
            dist_sq = (px - t * dx) ** 2 + (py - t * dy) ** 2
            nearest = np.argmin(dist_sq, axis=1)
            rows = np.arange(len(nearest))
            offsets[chunk] = np.sqrt(dist_sq[rows, nearest])
            along[chunk] = self.cumulative_miles[nearest] + t[rows, nearest] * segment_miles[nearest]
        return offsets, along
