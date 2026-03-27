from django.core.management.base import BaseCommand
from django.utils import timezone
from listings.models import MarketPriceBand


class Command(BaseCommand):
    help = "Seed MarketPriceBand with starter data"

    def handle(self, *args, **options):
        today = timezone.now().date()
        seed = [
            {
                "county": "Nairobi",
                "market_zone": "urban",
                "land_type": "residential",
                "listing_type": "sale",
                "area_unit": "acres",
                "min_price_per_unit": 20000000,
                "max_price_per_unit": 80000000,
            },
            {
                "county": "Nairobi",
                "market_zone": "urban",
                "land_type": "commercial",
                "listing_type": "sale",
                "area_unit": "acres",
                "min_price_per_unit": 30000000,
                "max_price_per_unit": 120000000,
            },
            {
                "county": "Nakuru",
                "market_zone": "rural",
                "land_type": "agricultural",
                "listing_type": "sale",
                "area_unit": "acres",
                "min_price_per_unit": 600000,
                "max_price_per_unit": 3000000,
            },
            {
                "county": "Kiambu",
                "market_zone": "peri_urban",
                "land_type": "agricultural",
                "listing_type": "sale",
                "area_unit": "acres",
                "min_price_per_unit": 1500000,
                "max_price_per_unit": 6000000,
            },
            {
                "county": "Uasin Gishu",
                "market_zone": "rural",
                "land_type": "agricultural",
                "listing_type": "sale",
                "area_unit": "acres",
                "min_price_per_unit": 800000,
                "max_price_per_unit": 3500000,
            },
            {
                "county": "Kajiado",
                "market_zone": "rural",
                "land_type": "agricultural",
                "listing_type": "lease",
                "area_unit": "acres",
                "min_price_per_unit": 8000,
                "max_price_per_unit": 15000,
            },
            {
                "county": "Kiambu",
                "market_zone": "peri_urban",
                "land_type": "residential",
                "listing_type": "sale",
                "area_unit": "acres",
                "min_price_per_unit": 5000000,
                "max_price_per_unit": 35000000,
            },
        ]
        created = 0
        for item in seed:
            obj, was_created = MarketPriceBand.objects.get_or_create(
                county=item["county"],
                subcounty=item.get("subcounty", ""),
                market_zone=item["market_zone"],
                land_type=item["land_type"],
                listing_type=item["listing_type"],
                area_unit=item["area_unit"],
                is_active=True,
                defaults={
                    **item,
                    "effective_from": today,
                    "source": "AgriPlot starter pricing guide",
                    "notes": "Seeded default band",
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} price bands"))
