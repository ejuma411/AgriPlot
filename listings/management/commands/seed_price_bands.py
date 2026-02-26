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
                "land_type": "residential",
                "listing_type": "sale",
                "min_price_per_acre": 20000000,
                "max_price_per_acre": 80000000,
            },
            {
                "county": "Nairobi",
                "land_type": "commercial",
                "listing_type": "sale",
                "min_price_per_acre": 30000000,
                "max_price_per_acre": 120000000,
            },
            {
                "county": "Nakuru",
                "land_type": "agricultural",
                "listing_type": "sale",
                "min_price_per_acre": 600000,
                "max_price_per_acre": 3000000,
            },
            {
                "county": "Kiambu",
                "land_type": "agricultural",
                "listing_type": "sale",
                "min_price_per_acre": 1500000,
                "max_price_per_acre": 6000000,
            },
            {
                "county": "Uasin Gishu",
                "land_type": "agricultural",
                "listing_type": "sale",
                "min_price_per_acre": 800000,
                "max_price_per_acre": 3500000,
            },
        ]
        created = 0
        for item in seed:
            obj, was_created = MarketPriceBand.objects.get_or_create(
                county=item["county"],
                land_type=item["land_type"],
                listing_type=item["listing_type"],
                effective_to__isnull=True,
                defaults={
                    **item,
                    "effective_from": today,
                    "notes": "Seeded default band",
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} price bands"))
