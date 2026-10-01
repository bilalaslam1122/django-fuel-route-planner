from django.contrib import admin

from .models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("opis_id", "name", "city", "state", "price_per_gallon", "coordinate_source")
    list_filter = ("state", "coordinate_source")
    search_fields = ("name", "city", "opis_id")
