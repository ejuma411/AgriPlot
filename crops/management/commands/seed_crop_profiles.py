from django.core.management.base import BaseCommand
from django.utils.text import slugify

from crops.models import CropProfile


CROP_TEST_DATA = [
    {
        "name": "Avocados (Hass)",
        "optimal_ph_min": "5.50",
        "optimal_ph_max": "6.50",
        "optimal_altitude_min_m": 1000,
        "optimal_altitude_max_m": 2000,
        "optimal_temperature_min_c": "16.00",
        "optimal_temperature_max_c": "24.00",
        "optimal_rainfall_min_mm": 1000,
        "optimal_rainfall_max_mm": 1200,
        "ideal_soil_types": "medium sandy loam, red volcanic, loam",
        "preferred_topographies": "gentle, valley",
        "irrigation_requirement": "moderate",
        "notes": "Strong export crop with good performance in well-drained volcanic zones.",
    },
    {
        "name": "Potatoes (Irish)",
        "optimal_ph_min": "5.20",
        "optimal_ph_max": "6.00",
        "optimal_altitude_min_m": 1500,
        "optimal_altitude_max_m": 3000,
        "optimal_temperature_min_c": "15.00",
        "optimal_temperature_max_c": "20.00",
        "optimal_rainfall_min_mm": 600,
        "optimal_rainfall_max_mm": 1200,
        "ideal_soil_types": "deep loam, loam, red volcanic",
        "preferred_topographies": "flat, gentle",
        "irrigation_requirement": "moderate",
        "notes": "Requires cool climates and well-drained soils.",
    },
    {
        "name": "Onions (Bulb)",
        "optimal_ph_min": "6.00",
        "optimal_ph_max": "7.00",
        "optimal_altitude_min_m": 0,
        "optimal_altitude_max_m": 2000,
        "optimal_temperature_min_c": "15.00",
        "optimal_temperature_max_c": "30.00",
        "optimal_rainfall_min_mm": 500,
        "optimal_rainfall_max_mm": 700,
        "ideal_soil_types": "fertile sandy loam, sandy loam, loam",
        "preferred_topographies": "flat, gentle",
        "irrigation_requirement": "high",
        "notes": "Performs best with irrigation and lighter soils.",
    },
    {
        "name": "Maize",
        "optimal_ph_min": "5.50",
        "optimal_ph_max": "7.00",
        "optimal_altitude_min_m": 0,
        "optimal_altitude_max_m": 2200,
        "optimal_temperature_min_c": "18.00",
        "optimal_temperature_max_c": "27.00",
        "optimal_rainfall_min_mm": 600,
        "optimal_rainfall_max_mm": 1200,
        "ideal_soil_types": "rich loam, alluvial, loam, red volcanic",
        "preferred_topographies": "flat, gentle, valley",
        "irrigation_requirement": "moderate",
        "notes": "Broad suitability crop and a good benchmark for mixed farming land.",
    },
    {
        "name": "French Beans",
        "optimal_ph_min": "6.00",
        "optimal_ph_max": "7.50",
        "optimal_altitude_min_m": 1000,
        "optimal_altitude_max_m": 2200,
        "optimal_temperature_min_c": "16.00",
        "optimal_temperature_max_c": "24.00",
        "optimal_rainfall_min_mm": 900,
        "optimal_rainfall_max_mm": 1200,
        "ideal_soil_types": "loam, sandy loam, alluvial",
        "preferred_topographies": "flat, gentle",
        "irrigation_requirement": "high",
        "notes": "High-value horticulture crop for irrigated small and medium plots.",
    },
]


class Command(BaseCommand):
    help = "Seed crop-condition profiles used by the crop suggestion engine."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for item in CROP_TEST_DATA:
            defaults = item.copy()
            defaults["slug"] = slugify(item["name"])
            crop, was_created = CropProfile.objects.update_or_create(
                slug=defaults["slug"],
                defaults=defaults,
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created {crop.name}"))
            else:
                updated += 1
                self.stdout.write(self.style.WARNING(f"Updated {crop.name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Crop profile seed complete. Created {created}, updated {updated}."
            )
        )
