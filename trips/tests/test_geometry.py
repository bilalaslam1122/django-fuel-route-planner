import numpy as np
from django.test import SimpleTestCase

from stations.geo import haversine_miles
from trips.geometry import RouteLine

# A straight east-west road along latitude 40, about 106 miles long.
ROAD = [(40.0, -100.0 + i * 0.01) for i in range(201)]
ROAD_MILES = haversine_miles(40.0, -100.0, 40.0, -98.0)


class RouteLineTests(SimpleTestCase):
    def line(self, road_miles=ROAD_MILES, spacing=1.0) -> RouteLine:
        return RouteLine.from_coordinates(ROAD, road_miles, spacing)

    def test_thinning_keeps_endpoints_and_reduces_points(self):
        line = self.line(spacing=5.0)

        self.assertLess(len(line.lat), len(ROAD))
        self.assertEqual((line.lat[0], line.lon[0]), ROAD[0])
        self.assertEqual((line.lat[-1], line.lon[-1]), ROAD[-1])

    def test_cumulative_distance_is_scaled_to_road_distance(self):
        line = self.line(road_miles=150.0)
        self.assertAlmostEqual(line.cumulative_miles[-1], 150.0)

    def test_projection_gives_offset_and_position_along_route(self):
        line = self.line()
        five_miles_north = 40.0 + 5 / 69.09

        offsets, along = line.project(np.array([five_miles_north, 40.0]), np.array([-99.0, -98.5]))

        self.assertAlmostEqual(offsets[0], 5.0, delta=0.1)
        self.assertAlmostEqual(along[0], ROAD_MILES / 2, delta=0.5)
        self.assertAlmostEqual(offsets[1], 0.0, delta=0.01)
        self.assertAlmostEqual(along[1], ROAD_MILES * 0.75, delta=0.5)

    def test_points_beyond_the_ends_clamp_to_the_ends(self):
        offsets, along = self.line().project(np.array([40.0]), np.array([-101.0]))

        self.assertAlmostEqual(along[0], 0.0)
        self.assertAlmostEqual(offsets[0], haversine_miles(40, -101, 40, -100), delta=0.2)

    def test_projection_handles_many_points_across_chunks(self):
        lons = np.linspace(-100, -98, 1000)
        offsets, along = self.line().project(np.full(1000, 40.0), lons)

        self.assertTrue(np.all(offsets < 0.01))
        self.assertTrue(np.all(np.diff(along) >= -1e-9))

    def test_geojson_is_lon_lat(self):
        geometry = self.line().geojson()

        self.assertEqual(geometry["type"], "LineString")
        self.assertEqual(geometry["coordinates"][0], [-100.0, 40.0])

    def test_bounding_box_includes_margin(self):
        lat_min, lat_max, lon_min, lon_max = self.line().bounding_box(10)

        self.assertLess(lat_min, 40.0 - 0.14)
        self.assertGreater(lon_max, -98.0 + 0.18)
