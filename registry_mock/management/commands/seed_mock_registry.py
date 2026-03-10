from django.core.management.base import BaseCommand
from registry_mock.models import MockLandRegistry
from listings.kenya_data import KENYA_COUNTIES
import random
from decimal import Decimal, ROUND_HALF_UP


class Command(BaseCommand):
    help = "Seed mock land registry records for Ardhisasa testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of registry records to create (default: 10)",
        )
        parser.add_argument(
            "--encumbrance-rate",
            type=float,
            default=0.2,
            help="Fraction of records to mark with charges/cautions (default: 0.2)",
        )
        parser.add_argument(
            "--preset",
            action="store_true",
            help="Seed a fixed set of realistic Kenya test parcels (clean/charged/cautioned)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        encumbrance_rate = options["encumbrance_rate"]
        preset = options["preset"]

        created = 0
        if preset:
            dummy_plots = [
                {
                    "parcel_number": "NAIROBI/BLOCK101/45",
                    "registered_owner_name": "John Kamau",
                    "owner_id_number": "12345678",
                    "owner_kra_pin": "A001234567Z",
                    "acreage_ha": Decimal("0.5000"),
                    "land_type": "FREEHOLD",
                    "is_charged": False,
                    "has_caution": False,
                },
                {
                    "parcel_number": "KIAMBU/KIKUYU/999",
                    "registered_owner_name": "Mary Wanjiku",
                    "owner_id_number": "87654321",
                    "owner_kra_pin": "A008765432X",
                    "acreage_ha": Decimal("1.2000"),
                    "land_type": "LEASEHOLD",
                    "is_charged": True,
                    "has_caution": False,
                },
                {
                    "parcel_number": "LR 1870/1/218",
                    "registered_owner_name": "Peter Omondi",
                    "owner_id_number": "11223344",
                    "owner_kra_pin": "A001122334P",
                    "acreage_ha": Decimal("2.5000"),
                    "land_type": "FREEHOLD",
                    "is_charged": False,
                    "has_caution": True,
                },
            ]
            for data in dummy_plots:
                obj, was_created = MockLandRegistry.objects.get_or_create(
                    parcel_number=data["parcel_number"],
                    defaults=data,
                )
                if was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"Created preset registry record: {obj.parcel_number}"))
            self.stdout.write(self.style.SUCCESS(f"Done. Created {created} preset registry record(s)."))
            return

        attempts = 0
        max_attempts = count * 5

        while created < count and attempts < max_attempts:
            attempts += 1
            county = random.choice(KENYA_COUNTIES)
            parcel_number = f"{county.upper()}/{random.randint(100,999)}/{random.randint(1,9999)}"
            if MockLandRegistry.objects.filter(parcel_number__iexact=parcel_number).exists():
                continue

            acreage_ha = Decimal(str(random.uniform(0.5, 20.0))).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            has_issue = random.random() < encumbrance_rate

            record = MockLandRegistry(
                parcel_number=parcel_number,
                registered_owner_name=f"Registry Owner {random.randint(1, 999)}",
                owner_id_number=str(random.randint(10000000, 99999999)),
                owner_kra_pin=f"A{random.randint(100000000, 999999999)}",
                acreage_ha=acreage_ha,
                land_type=random.choice(["FREEHOLD", "LEASEHOLD"]),
                is_charged=has_issue and random.random() < 0.6,
                has_caution=has_issue and random.random() < 0.6,
            )
            record.save()
            created += 1
            self.stdout.write(self.style.SUCCESS(f"Created registry record: {record.parcel_number}"))

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} registry record(s)."))
