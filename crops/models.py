from django.db import models


class CropProfile(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    optimal_ph_min = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    optimal_ph_max = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    optimal_altitude_min_m = models.PositiveIntegerField(null=True, blank=True)
    optimal_altitude_max_m = models.PositiveIntegerField(null=True, blank=True)
    optimal_temperature_min_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    optimal_temperature_max_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    optimal_rainfall_min_mm = models.PositiveIntegerField(null=True, blank=True)
    optimal_rainfall_max_mm = models.PositiveIntegerField(null=True, blank=True)
    ideal_soil_types = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated soil labels such as Red Volcanic, Loam, Sandy Loam.",
    )
    preferred_topographies = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated topography labels such as flat, gentle, valley.",
    )
    irrigation_requirement = models.CharField(
        max_length=20,
        choices=[
            ("low", "Low"),
            ("moderate", "Moderate"),
            ("high", "High"),
        ],
        default="moderate",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"]),
        ]

    def __str__(self):
        return self.name
