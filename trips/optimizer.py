"""Minimum-cost refuelling along a fixed route.

Stations are points on a line (their distance from the start). The vehicle
starts with a full tank, so the start is modelled as a free "station" where the
tank is already full. At each stop the classic greedy rule for this problem
(provably optimal for a single route with a tank limit) applies:

1. If a cheaper station is reachable on a full tank, buy only enough fuel to
   reach the first such station: any extra would cost more than buying there.
2. Otherwise, if the destination is reachable on a full tank, buy only enough
   to finish.
3. Otherwise this is the cheapest fuel in range: fill the tank and drive to the
   cheapest station within range (the farthest of equal-price stations).

If no station is in range and the destination isn't either, there is no
feasible plan. Distances and fuel are floats in miles/gallons; money is
handled with Decimal in `cost_of`.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

EPSILON_MILES = 1e-6
GALLONS_PRECISION = Decimal("0.001")
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Vehicle:
    max_range_miles: float = 500.0
    miles_per_gallon: float = 10.0

    @property
    def tank_capacity_gallons(self) -> float:
        return self.max_range_miles / self.miles_per_gallon


@dataclass(frozen=True)
class FuelCandidate:
    station_id: int
    position_miles: float  # road distance from the start
    price_per_gallon: Decimal


@dataclass(frozen=True)
class PlannedStop:
    candidate: FuelCandidate
    fuel_on_arrival_gallons: float
    gallons_purchased: float


@dataclass(frozen=True)
class FuelPlan:
    stops: list[PlannedStop]
    fuel_used_gallons: float
    fuel_at_finish_gallons: float


class NoFeasiblePlan(Exception):
    def __init__(self, stranded_at_miles: float, gap_miles: float | None) -> None:
        self.stranded_at_miles = stranded_at_miles
        self.gap_miles = gap_miles  # distance to the next station or finish, if known
        super().__init__(f"No reachable fuel station beyond mile {stranded_at_miles:.1f}")


def plan_fuel_stops(
    total_miles: float, candidates: list[FuelCandidate], vehicle: Vehicle = Vehicle()
) -> FuelPlan:
    capacity = vehicle.max_range_miles
    stations = _cheapest_per_position(c for c in candidates if 0 <= c.position_miles <= total_miles)
    positions = [s.position_miles for s in stations]

    position, fuel_miles = 0.0, capacity  # starts with a full tank
    current: FuelCandidate | None = None  # None while still at the start
    stops: list[PlannedStop] = []

    while True:
        # From the start nothing can be bought, but the tank is already full.
        first_ahead = bisect_right(positions, position + EPSILON_MILES)
        last_in_range = bisect_right(positions, position + capacity + EPSILON_MILES)
        in_range = stations[first_ahead:last_in_range]
        price = current.price_per_gallon if current else None

        cheaper = next((s for s in in_range if price is not None and s.price_per_gallon < price), None)
        if cheaper is not None:
            target_position, buy_to_miles, next_station = cheaper.position_miles, None, cheaper
        elif total_miles <= position + capacity + EPSILON_MILES:
            target_position, buy_to_miles, next_station = total_miles, None, None
        elif in_range:
            next_station = min(in_range, key=lambda s: (s.price_per_gallon, -s.position_miles))
            target_position, buy_to_miles = next_station.position_miles, capacity
        else:
            gap = (positions[first_ahead] if first_ahead < len(positions) else total_miles) - position
            raise NoFeasiblePlan(position, gap)

        leg = target_position - position
        wanted = buy_to_miles if buy_to_miles is not None else leg
        purchase = max(0.0, wanted - fuel_miles) if current else 0.0
        if purchase > EPSILON_MILES and current is not None:
            stops.append(
                PlannedStop(
                    candidate=current,
                    fuel_on_arrival_gallons=fuel_miles / vehicle.miles_per_gallon,
                    gallons_purchased=purchase / vehicle.miles_per_gallon,
                )
            )
        fuel_miles = fuel_miles + purchase - leg
        position, current = target_position, next_station
        if next_station is None:
            return FuelPlan(
                stops=stops,
                fuel_used_gallons=total_miles / vehicle.miles_per_gallon,
                fuel_at_finish_gallons=max(0.0, fuel_miles) / vehicle.miles_per_gallon,
            )


def _cheapest_per_position(candidates) -> list[FuelCandidate]:
    """Stations sharing a position (same city) collapse to the cheapest one."""
    best: dict[float, FuelCandidate] = {}
    for c in candidates:
        key = round(c.position_miles, 2)
        if key not in best or c.price_per_gallon < best[key].price_per_gallon:
            best[key] = c
    return sorted(best.values(), key=lambda c: c.position_miles)


def round_gallons(gallons: float) -> Decimal:
    return Decimal(repr(gallons)).quantize(GALLONS_PRECISION, rounding=ROUND_HALF_UP)


def cost_of(gallons: float, price_per_gallon: Decimal) -> Decimal:
    """Cost of a purchase in dollars, using the gallons as displayed (3 dp)."""
    return (round_gallons(gallons) * price_per_gallon).quantize(CENTS, rounding=ROUND_HALF_UP)
