from django.db import models


class CoordinateSource(models.TextChoices):
    """Where a station's coordinates came from (the supplied CSV has none)."""

    CENSUS_PLACE = "census_place", "US Census Gazetteer place"
    CENSUS_COUNTY_SUBDIVISION = "census_cousub", "US Census Gazetteer county subdivision"
    NOMINATIM = "nominatim", "Nominatim geocoder"


class FuelStation(models.Model):
    """One fuel station from the supplied OPIS price file, deduplicated by OPIS id.

    Coordinates are city-level (the dataset only provides highway/exit addresses),
    so they approximate the station's position to within a few miles.
    """

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    price_per_gallon = models.DecimalField(max_digits=8, decimal_places=5)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    coordinate_source = models.CharField(
        max_length=20, choices=CoordinateSource.choices, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["opis_id"]
        indexes = [models.Index(fields=["state", "city"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_per_gallon__gt=0), name="fuel_price_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.price_per_gallon}"

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None
