from django.core.management.base import BaseCommand

from listings.models import HealthFacility, Market, Road, School, WaterSource


class Command(BaseCommand):
    help = "Seed sample amenity layers for local GIS and map demos."

    def handle(self, *args, **options):
        samples = {
            WaterSource: [
                {"name": "Community Borehole", "longitude": 36.8219, "latitude": -1.2921, "description": "Shared borehole"},
                {"name": "Seasonal Stream", "longitude": 35.9911, "latitude": -0.3031, "description": "Seasonal stream"},
            ],
            Road: [
                {"name": "A104 Access", "longitude": 36.0683, "latitude": -0.3032, "road_type": "tarmac"},
                {"name": "Murram Link Road", "longitude": 37.0722, "latitude": -1.0396, "road_type": "murram"},
            ],
            Market: [
                {"name": "Farmers Market", "longitude": 36.9580, "latitude": -0.4201, "description": "Fresh produce market"},
                {"name": "Livestock Exchange", "longitude": 37.6559, "latitude": 0.0463, "description": "Livestock trading center"},
            ],
            School: [
                {"name": "Maua Primary", "longitude": 37.9392, "latitude": 0.2332, "level": "Primary"},
                {"name": "Rift Valley High", "longitude": 35.6117, "latitude": -0.1613, "level": "Secondary"},
            ],
            HealthFacility: [
                {"name": "County Dispensary", "longitude": 36.0678, "latitude": -0.3030, "facility_type": "Dispensary"},
                {"name": "Mission Hospital", "longitude": 37.0728, "latitude": -1.0390, "facility_type": "Hospital"},
            ],
        }

        created_total = 0
        for model, rows in samples.items():
            for row in rows:
                _, created = model.objects.get_or_create(name=row["name"], defaults=row)
                created_total += int(created)

        self.stdout.write(self.style.SUCCESS(f"Seeded {created_total} amenity records."))
