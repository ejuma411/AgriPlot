from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from django.utils import timezone
from listings.models import (
    Plot,
    LandownerProfile,
    LandSurveyor,
    ExtensionOfficer,
    VerificationTask,
    SurveyorReport,
    ExtensionReport,
)
from listings.verification_service import VerificationService
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
        parser.add_argument(
            "--with-reports",
            action="store_true",
            help="Create sample surveyor and extension reports for seeded plots",
        )

    def handle(self, *args, **options):
        count = options["count"]
        encumbrance_rate = options["encumbrance_rate"]
        with_reports = options["with_reports"]

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
        created_plots = []

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
                owner_kra_pin_number=f"A{random.randint(100000000, 999999999)}",
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
                created_plots.append(plot)
                self.stdout.write(self.style.SUCCESS(f"Created registry plot: {plot.title} ({plot.parcel_number})"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipped plot due to error: {e}"))

        if with_reports and created_plots:
            surveyor_user, _ = User.objects.get_or_create(
                username="registry_surveyor",
                defaults={
                    "email": "registry_surveyor@example.com",
                    "first_name": "Registry",
                    "last_name": "Surveyor",
                },
            )
            extension_user, _ = User.objects.get_or_create(
                username="registry_extension",
                defaults={
                    "email": "registry_extension@example.com",
                    "first_name": "Registry",
                    "last_name": "Officer",
                },
            )

            surveyor, _ = LandSurveyor.objects.get_or_create(
                user=surveyor_user,
                defaults={
                    "license_number": "LSB/REG/001",
                    "designation": "Licensed Land Surveyor",
                    "station": "Nairobi",
                    "qualifications": "BSc Surveying",
                    "years_of_experience": 8,
                    "phone": "+254700000001",
                    "office_address": "Survey of Kenya HQ",
                    "assigned_counties": KENYA_COUNTIES[:5],
                    "verified": True,
                },
            )

            officer, _ = ExtensionOfficer.objects.get_or_create(
                user=extension_user,
                defaults={
                    "employee_id": "EXT/REG/001",
                    "designation": "Agricultural Officer",
                    "department": "Ministry of Agriculture",
                    "station": "Nairobi",
                    "qualifications": "BSc Agriculture",
                    "years_of_experience": 6,
                    "phone": "+254700000002",
                    "office_address": "County Agriculture Office",
                    "assigned_counties": KENYA_COUNTIES[:5],
                    "verified": True,
                },
            )

            for plot in created_plots:
                # Surveyor task and report
                surveyor_task, created_task = VerificationTask.objects.get_or_create(
                    plot=plot,
                    verification_type="surveyor_inspection",
                    defaults={
                        "status": "completed",
                        "assigned_to": surveyor_user,
                        "completed_at": timezone.now(),
                        "approved": True,
                    },
                )
                if created_task:
                    surveyor_task.status = "completed"
                    surveyor_task.completed_at = timezone.now()
                    surveyor_task.approved = True
                    surveyor_task.save(update_fields=["status", "completed_at", "approved"])

                if not SurveyorReport.objects.filter(task=surveyor_task).exists():
                    report = SurveyorReport(
                        task=surveyor_task,
                        surveyor=surveyor,
                        plot=plot,
                        visit_date=timezone.now(),
                        boundary_confirmed=True,
                        acreage_confirmed=True,
                        encumbrances_found=plot.encumbrances,
                        encumbrance_details=plot.encumbrance_details,
                        beacon_status="all_present",
                        rim_map_sheet_no=f"RIM-{random.randint(100, 999)}",
                        ground_acreage=Decimal(str(round(random.uniform(2.0, 20.0), 4))),
                        deed_area=Decimal(str(round(random.uniform(2.0, 20.0), 4))),
                        lsb_license_number=surveyor.license_number,
                        encroachment_found=bool(random.random() < 0.2),
                        encroachment_details="Minor boundary overlap on eastern edge",
                        recommendation="approve",
                    )
                    report.mutation_form.save(
                        f"mutation_form_{uuid.uuid4().hex}.pdf",
                        ContentFile(b"Dummy mutation form"),
                        save=False,
                    )
                    report.beacon_certificate.save(
                        f"beacon_cert_{uuid.uuid4().hex}.pdf",
                        ContentFile(b"Dummy beacon certificate"),
                        save=False,
                    )
                    report.save()

                # Extension task and report
                extension_task, created_task = VerificationTask.objects.get_or_create(
                    plot=plot,
                    verification_type="extension_review",
                    defaults={
                        "status": "completed",
                        "assigned_to": extension_user,
                        "completed_at": timezone.now(),
                        "approved": True,
                    },
                )
                if created_task:
                    extension_task.status = "completed"
                    extension_task.completed_at = timezone.now()
                    extension_task.approved = True
                    extension_task.save(update_fields=["status", "completed_at", "approved"])

                if not ExtensionReport.objects.filter(task=extension_task).exists():
                    ExtensionReport.objects.create(
                        task=extension_task,
                        officer=officer,
                        plot=plot,
                        visit_date=timezone.now(),
                        weather_conditions="Clear",
                        soil_ph=Decimal("6.5"),
                        soil_classification="Red Volcanic",
                        soil_texture="loamy",
                        soil_drainage="good",
                        topography="gentle",
                        current_land_use="Mixed subsistence crops",
                        water_source_verified="Borehole",
                        water_quality="good",
                        irrigation_system="Drip",
                        power_access="grid",
                        zoning_status="agricultural",
                        lcb_zone=True,
                        lcb_approval_potential="likely",
                        recommended_crops="Maize, Beans",
                        improvement_suggestions="Add soil organic matter",
                        overall_suitability="highly_suitable",
                        recommendation="approve",
                        comments="Suitable for commercial agriculture.",
                    )

                VerificationService.finalize_verification_if_ready(plot)

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} registry plot(s)."))
