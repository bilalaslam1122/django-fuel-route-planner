import random
from decimal import Decimal

from django.test import SimpleTestCase

from trips.optimizer import FuelCandidate, NoFeasiblePlan, Vehicle, cost_of, plan_fuel_stops

VEHICLE = Vehicle(max_range_miles=500, miles_per_gallon=10)


def station(station_id: int, miles: float, price: str) -> FuelCandidate:
    return FuelCandidate(station_id, miles, Decimal(price))


def trip_cost(plan) -> Decimal:
    return sum(
        (s.candidate.price_per_gallon * Decimal(repr(s.gallons_purchased)) for s in plan.stops), Decimal(0)
    )


class FuelPlanTests(SimpleTestCase):
    def test_route_under_500_miles_needs_no_stop(self):
        plan = plan_fuel_stops(300, [station(1, 100, "2.00")], VEHICLE)

        self.assertEqual(plan.stops, [])
        self.assertAlmostEqual(plan.fuel_used_gallons, 30)
        self.assertAlmostEqual(plan.fuel_at_finish_gallons, 20)

    def test_route_of_exactly_500_miles_needs_no_stop(self):
        plan = plan_fuel_stops(500, [], VEHICLE)

        self.assertEqual(plan.stops, [])
        self.assertAlmostEqual(plan.fuel_at_finish_gallons, 0)

    def test_route_over_500_miles_requires_a_stop(self):
        plan = plan_fuel_stops(600, [station(1, 400, "3.00")], VEHICLE)

        self.assertEqual(len(plan.stops), 1)
        stop = plan.stops[0]
        self.assertAlmostEqual(stop.fuel_on_arrival_gallons, 10)  # 500 - 400 miles left
        self.assertAlmostEqual(stop.gallons_purchased, 10)  # exactly enough for the last 200 miles
        self.assertAlmostEqual(plan.fuel_at_finish_gallons, 0)

    def test_multiple_stops_on_a_long_route(self):
        stations = [station(i, miles, "3.00") for i, miles in enumerate([300, 600, 900, 1200, 1500], 1)]

        plan = plan_fuel_stops(1700, stations, VEHICLE)

        self.assertGreaterEqual(len(plan.stops), 3)
        bought = sum(s.gallons_purchased for s in plan.stops)
        self.assertAlmostEqual(bought, 170 - 50)  # fuel used minus the starting tank

    def test_prefers_cheaper_reachable_station_over_nearer_one(self):
        # From the assignment brief: A at 300 mi for $3.50, B at 380 mi for $3.00.
        plan = plan_fuel_stops(700, [station(1, 300, "3.50"), station(2, 380, "3.00")], VEHICLE)

        self.assertEqual([s.candidate.station_id for s in plan.stops], [2])
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 20)

    def test_cheap_but_unreachable_station_forces_a_small_purchase_before_it(self):
        plan = plan_fuel_stops(800, [station(1, 100, "4.00"), station(2, 510, "2.00")], VEHICLE)

        ids = [s.candidate.station_id for s in plan.stops]
        self.assertEqual(ids, [1, 2])
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 1)  # only enough to reach B
        self.assertAlmostEqual(plan.stops[1].gallons_purchased, 29)  # B -> finish

    def test_cheap_station_near_the_range_limit_is_still_used_when_safe(self):
        plan = plan_fuel_stops(900, [station(1, 100, "4.00"), station(2, 490, "3.00")], VEHICLE)

        self.assertEqual([s.candidate.station_id for s in plan.stops], [2])
        self.assertAlmostEqual(plan.stops[0].fuel_on_arrival_gallons, 1)
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 40)

    def test_fills_up_at_cheap_station_when_only_dearer_fuel_lies_ahead(self):
        plan = plan_fuel_stops(1100, [station(1, 400, "2.50"), station(2, 800, "4.00")], VEHICLE)

        first, second = plan.stops
        self.assertAlmostEqual(first.gallons_purchased, 40)  # tank filled to 50
        self.assertAlmostEqual(second.gallons_purchased, 20)  # only what's needed at $4

    def test_no_reachable_station_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan) as ctx:
            plan_fuel_stops(1200, [station(1, 300, "3.00")], VEHICLE)

        self.assertAlmostEqual(ctx.exception.stranded_at_miles, 300)
        self.assertAlmostEqual(ctx.exception.gap_miles, 900)

    def test_no_stations_at_all_on_a_long_route_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan) as ctx:
            plan_fuel_stops(501, [], VEHICLE)
        self.assertEqual(ctx.exception.stranded_at_miles, 0)

    def test_destination_reachable_from_last_station(self):
        plan = plan_fuel_stops(990, [station(1, 495, "3.00")], VEHICLE)

        self.assertAlmostEqual(plan.stops[-1].fuel_on_arrival_gallons, 0.5)
        self.assertAlmostEqual(plan.stops[-1].gallons_purchased, 49)  # 495 miles still to go
        self.assertAlmostEqual(plan.fuel_at_finish_gallons, 0)

    def test_stations_outside_the_route_span_are_ignored(self):
        plan = plan_fuel_stops(300, [station(1, -5, "1.00"), station(2, 900, "1.00")], VEHICLE)
        self.assertEqual(plan.stops, [])

    def test_stations_at_the_same_position_use_the_cheapest(self):
        plan = plan_fuel_stops(700, [station(1, 400, "3.50"), station(2, 400, "3.10")], VEHICLE)
        self.assertEqual([s.candidate.station_id for s in plan.stops], [2])

    def test_matches_brute_force_optimum_on_random_routes(self):
        rng = random.Random(42)
        for _ in range(150):
            total = rng.randrange(510, 1500, 10)
            positions = sorted(rng.sample(range(10, total, 10), k=min(6, total // 10 - 1)))
            stations = [station(i, p, f"{rng.uniform(2.5, 4.5):.2f}") for i, p in enumerate(positions)]
            expected = _brute_force_min_cost(total, stations)
            with self.subTest(total=total, stations=stations):
                if expected is None:
                    with self.assertRaises(NoFeasiblePlan):
                        plan_fuel_stops(total, stations, VEHICLE)
                else:
                    self.assertAlmostEqual(float(trip_cost(plan_fuel_stops(total, stations, VEHICLE))), float(expected), places=6)


def _brute_force_min_cost(total: int, stations: list[FuelCandidate]) -> Decimal | None:
    """Exact DP over whole gallons (positions are multiples of 10 miles = 1 gallon)."""
    best = {50: Decimal(0)}  # fuel in tank (gallons) at the start
    previous = 0
    for s in [*stations, None]:
        position = total if s is None else int(s.position_miles)
        used = (position - previous) // 10
        arrived = {fuel - used: cost for fuel, cost in best.items() if fuel >= used}
        if not arrived:
            return None
        if s is None:
            return min(arrived.values())
        best = {}
        for fuel, cost in arrived.items():
            for buy in range(0, 51 - fuel):
                key = fuel + buy
                value = cost + s.price_per_gallon * buy
                if key not in best or value < best[key]:
                    best[key] = value
        previous = position
    return None


class CostTests(SimpleTestCase):
    def test_cost_uses_decimal_and_rounds_half_up_to_cents(self):
        self.assertEqual(cost_of(31.05, Decimal("3.19")), Decimal("99.05"))  # 99.0495
        self.assertEqual(cost_of(0.1 + 0.2, Decimal("3.00")), Decimal("0.90"))  # float noise removed

    def test_cost_of_fractional_price(self):
        self.assertEqual(cost_of(10, Decimal("3.00733")), Decimal("30.07"))

