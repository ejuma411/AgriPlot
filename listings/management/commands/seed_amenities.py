from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from listings.models import HealthFacility, Market, Road, School, WaterSource


class Command(BaseCommand):
    help = "Seed sample amenity layers for local GIS and map demos."

    def handle(self, *args, **options):
        samples = {
            WaterSource: [
                {"name": "Community Borehole", "location": Point(36.8219, -1.2921, srid=4326), "description": "Shared borehole"},
                {"name": "Seasonal Stream", "location": Point(35.9911, -0.3031, srid=4326), "description": "Seasonal stream"},
            ],
            Road: [
                {"name": "A104 Access", "location": Point(36.0683, -0.3032, srid=4326), "road_type": "tarmac"},
                {"name": "Murram Link Road", "location": Point(37.0722, -1.0396, srid=4326), "road_type": "murram"},
            ],
            Market: [
                {"name": "Farmers Market", "location": Point(36.9580, -0.4201, srid=4326), "description": "Fresh produce market"},
                {"name": "Livestock Exchange", "location": Point(37.6559, 0.0463, srid=4326), "description": "Livestock trading center"},
            ],
            School: [
                {"name": "Maua Primary", "location": Point(37.9392, 0.2332, srid=4326), "level": "Primary"},
                {"name": "Rift Valley High", "location": Point(35.6117, -0.1613, srid=4326), "level": "Secondary"},
            ],
            HealthFacility: [
                {"name": "County Dispensary", "location": Point(36.0678, -0.3030, srid=4326), "facility_type": "Dispensary"},
                {"name": "Mission Hospital", "location": Point(37.0728, -1.0390, srid=4326), "facility_type": "Hospital"},
            ],
        }

        created_total = 0
        for model, rows in samples.items():
            for row in rows:
                _, created = model.objects.get_or_create(name=row["name"], defaults=row)
                created_total += int(created)

        self.stdout.write(self.style.SUCCESS(f"Seeded {created_total} amenity records."))
