from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from django.utils import timezone
from listings.models import Plot, LandownerProfile
from listings.kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES
import random
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta


class Command(BaseCommand):
    help = "Seed registry plots for land search testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of registry plots to create (default: 10)",
        )
        parser.add_argument(
            "--encumbrance-rate",
            type=float,
            default=0.2,
            help="Fraction of plots to mark with encumbrances (default: 0.2)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        encumbrance_rate = options["encumbrance_rate"]

        user, _ = User.objects.get_or_create(
            username="registry_owner",
            defaults={
                "email": "registry_owner@example.com",
                "first_name": "Registry",
                "last_name": "Owner",
            },
        )

        landowner, _ = LandownerProfile.objects.get_or_create(
            user=user,
            defaults={
                "verified": True,
            },
        )

        # Attach required landowner docs if missing
        if not landowner.national_id:
            landowner.national_id.save("registry_national_id.pdf", ContentFile(b"Dummy ID"), save=True)
        if not landowner.kra_pin:
            landowner.kra_pin.save("registry_kra_pin.pdf", ContentFile(b"Dummy KRA"), save=True)
        if not landowner.title_deed:
            landowner.title_deed.save("registry_title_deed.pdf", ContentFile(b"Dummy Title"), save=True)
        if not landowner.land_search:
            landowner.land_search.save("registry_land_search.pdf", ContentFile(b"Dummy Search"), save=True)

        titles = [
            "Registry Plot - Kitale",
            "Registry Plot - Eldoret",
            "Registry Plot - Nakuru",
            "Registry Plot - Narok",
            "Registry Plot - Thika",
            "Registry Plot - Meru",
            "Registry Plot - Naivasha",
            "Registry Plot - Bungoma",
            "Registry Plot - Machakos",
            "Registry Plot - Nyeri",
        ]

        created = 0
        attempts = 0
        max_attempts = count * 5

        while created < count and attempts < max_attempts:
            attempts += 1
            county = random.choice(KENYA_COUNTIES)
            subcounty = random.choice(KENYA_SUB_COUNTIES.get(county, [county]))
            area = round(random.uniform(2.0, 20.0), 2)
            area_unit = random.choice(["acres", "hectares"])
            has_encumbrance = random.random() < encumbrance_rate

            parcel_number = f"{county.upper()}/{random.randint(100,999)}/{random.randint(1,9999)}"
            if Plot.objects.filter(parcel_number__iexact=parcel_number).exists():
                continue

            sale_price = Decimal(str(random.uniform(500000, 8000000))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            plot = Plot(
                title=random.choice(titles) + f" #{created + 1}",
                location=f"{county} - {subcounty}",
                county=county,
                subcounty=subcounty,
                nearest_town=subcounty,
                ownership_type="freehold",
                tenure_details="99-year lease",
                encumbrances=has_encumbrance,
                encumbrance_details="Charge: Registry Simulation Bank" if has_encumbrance else "",
                landowner=landowner,
                owner_full_name=f"{user.first_name} {user.last_name}".strip() or "Registry Owner",
                owner_id_number=str(random.randint(10000000, 99999999)),
                spousal_consent=bool(random.random() < 0.5),
                listing_type="sale",
                land_type="agricultural",
                land_use_description="Registry seed plot for testing",
                sale_price=sale_price,
                price=sale_price,
                area=area,
                area_unit=area_unit,
                parcel_number=parcel_number,
                registration_section=f"{county}/Block {random.randint(1,50)}",
                search_certificate_date=timezone.now().date() - timedelta(days=random.randint(1, 25)),
                search_reference_number=f"SRCH-{uuid.uuid4().hex[:10].upper()}",
                is_published=False,
                is_registry_record=True,
                created_at=timezone.now(),
            )

            # Required documents
            plot.title_deed.save(f"title_deed_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy title deed"), save=False)
            plot.survey_map.save(f"survey_map_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy survey map"), save=False)
            if plot.spousal_consent:
                plot.spousal_consent_doc.save(f"spousal_consent_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy spousal consent"), save=False)
            plot.official_search.save(f"official_search_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy official search"), save=False)
            plot.rates_clearance.save(f"rates_clearance_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy rates clearance"), save=False)
            plot.rent_clearance.save(f"rent_clearance_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy rent clearance"), save=False)
            plot.landowner_id_doc.save(f"landowner_id_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy landowner ID"), save=False)
            plot.kra_pin.save(f"kra_pin_{uuid.uuid4().hex}.pdf", ContentFile(b"Dummy KRA PIN"), save=False)

            try:
                plot.save()
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created registry plot: {plot.title} ({plot.parcel_number})"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipped plot due to error: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} registry plot(s)."))
