"""In-memory index of fuel stations for fast route matching.

~6.6k stations fit comfortably in memory as numpy arrays. The index is built on
first use and rebuilt automatically after `import_fuel_data` changes the table
(checked with one cheap aggregate query per request).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from django.db.models import Count, Max

from stations.models import FuelStation


@dataclass(frozen=True)
class StationIndex:
    stations: list[FuelStation]
    lat: np.ndarray
    lon: np.ndarray

    def within_box(self, box: tuple[float, float, float, float]) -> np.ndarray:
        lat_min, lat_max, lon_min, lon_max = box
        return np.flatnonzero(
            (self.lat >= lat_min) & (self.lat <= lat_max) & (self.lon >= lon_min) & (self.lon <= lon_max)
        )


_lock = threading.Lock()
_cached: tuple[tuple, StationIndex] | None = None


def get_station_index() -> StationIndex:
    global _cached
    located = FuelStation.objects.filter(latitude__isnull=False, longitude__isnull=False)
    version = tuple(located.aggregate(n=Count("id"), changed=Max("updated_at")).values())
    if _cached and _cached[0] == version:
        return _cached[1]
    with _lock:
        if _cached and _cached[0] == version:
            return _cached[1]
        stations = list(located.order_by("opis_id"))
        index = StationIndex(
            stations=stations,
            lat=np.array([s.latitude for s in stations], dtype=float),
            lon=np.array([s.longitude for s in stations], dtype=float),
        )
        _cached = (version, index)
        return index
