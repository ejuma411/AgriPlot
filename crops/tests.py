from django.test import TestCase

from crops.models import CropProfile
from crops.services import suggest_crops


class CropSuggestionServiceTests(TestCase):
    def setUp(self):
        CropProfile.objects.create(
            name="Maize",
            slug="maize",
            optimal_ph_min="5.50",
            optimal_ph_max="7.00",
            ideal_soil_types="loam, alluvial",
            preferred_topographies="flat, gentle",
            irrigation_requirement="moderate",
        )
        CropProfile.objects.create(
            name="Avocados (Hass)",
            slug="avocados-hass",
            optimal_ph_min="5.50",
            optimal_ph_max="6.50",
            ideal_soil_types="red volcanic, loam",
            preferred_topographies="gentle, valley",
            irrigation_requirement="moderate",
        )

    def test_rule_engine_returns_best_matches_first(self):
        suggestions = suggest_crops(
            soil_ph=6.2,
            soil_classification="Red Volcanic",
            soil_texture="Loam",
            topography="gentle",
            irrigation_viability="moderate",
        )

        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["crop"].name, "Avocados (Hass)")

    def test_rule_engine_returns_empty_when_no_profiles_exist(self):
        CropProfile.objects.all().delete()

        suggestions = suggest_crops(
            soil_ph=6.5,
            soil_classification="Loam",
            soil_texture="Loam",
            topography="flat",
        )

        self.assertEqual(suggestions, [])
