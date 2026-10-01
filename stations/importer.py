"""Persist parsed fuel stations, attaching city-level coordinates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import transaction

from .city_coordinates import CityCoordinate, CityKey, normalize_city
from .fuel_data import StationRecord
from .models import FuelStation

UPDATE_FIELDS = [
    "name", "address", "city", "state", "rack_id", "price_per_gallon",
    "latitude", "longitude", "coordinate_source", "updated_at",
]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    without_coordinates: list[StationRecord] = field(default_factory=list)


@transaction.atomic
def sync_stations(
    records: Iterable[StationRecord], coordinates: dict[CityKey, CityCoordinate]
) -> SyncResult:
    """Make the FuelStation table mirror `records` exactly.

    Upserts on `opis_id` and removes stations no longer in the file, so running
    it repeatedly with the same input is a no-op.
    """
    result = SyncResult()
    existing_ids = set(FuelStation.objects.values_list("opis_id", flat=True))
    stations: list[FuelStation] = []
    for record in records:
        coordinate = coordinates.get((record.state, normalize_city(record.city)))
        if coordinate is None:
            result.without_coordinates.append(record)
        stations.append(
            FuelStation(
                opis_id=record.opis_id,
                name=record.name,
                address=record.address,
                city=record.city,
                state=record.state,
                rack_id=record.rack_id,
                price_per_gallon=record.price_per_gallon,
                latitude=coordinate.latitude if coordinate else None,
                longitude=coordinate.longitude if coordinate else None,
                coordinate_source=coordinate.source if coordinate else "",
            )
        )

    incoming_ids = {s.opis_id for s in stations}
    result.deleted, _ = FuelStation.objects.exclude(opis_id__in=incoming_ids).delete()
    FuelStation.objects.bulk_create(
        stations,
        batch_size=500,
        update_conflicts=True,
        unique_fields=["opis_id"],
        update_fields=UPDATE_FIELDS,
    )
    result.updated = len(incoming_ids & existing_ids)
    result.created = len(incoming_ids - existing_ids)
    return result
