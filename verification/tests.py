import tempfile
from shutil import rmtree

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import LandownerProfile, Profile
from listings.models import Plot, PlotImage
from verification.models import LandSurveyor, VerificationTask
from verification.services.ocr_service import DocumentOCRService


class VerificationNamespaceTests(TestCase):
    def test_verification_dashboard_reverse(self):
        url = reverse("verification:verification_dashboard")
        self.assertTrue(url.startswith("/verify/verification/"))

    def test_staff_namespace_no_longer_exposes_duplicate_verification_route(self):
        response = self.client.get("/staff/verify/verification/")
        self.assertEqual(response.status_code, 404)


class SurveyorUploadTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()

    def tearDown(self):
        rmtree(self.temp_media, ignore_errors=True)

    def test_surveyor_report_upload_persists_plot_images(self):
        with override_settings(MEDIA_ROOT=self.temp_media):
            user = get_user_model().objects.create_user(
                username="surveyor_user",
                password="secret123",
            )
            Profile.objects.get_or_create(user=user, defaults={"role": "surveyor"})
            surveyor = LandSurveyor.objects.create(
                user=user,
                license_number="LSB-001",
                designation="County Surveyor",
                station="Nakuru",
                qualifications="BSc Survey",
                years_of_experience=5,
                phone="0712345678",
                assigned_counties=["Nakuru"],
                verified=True,
            )
            owner = get_user_model().objects.create_user(
                username="",
                password="",
            )
            Profile.objects.get_or_create(user=owner, defaults={"role": "landowner"})
            landowner = LandownerProfile.objects.create(
                user=owner,
                national_id=SimpleUploadedFile("owner_id.txt", b"id"),
                kra_pin=SimpleUploadedFile("owner_pin.txt", b"pin"),
            )
            plot = Plot.objects.create(
                landowner=landowner,
                title="Survey Image Plot",
                location="Nakuru",
                area=2.0,
                price="800000.00",
                sale_price="800000.00",
                listing_type="sale",
            )
            task = VerificationTask.objects.create(
                plot=plot,
                verification_type="surveyor_inspection",
                assigned_to=user,
                status="in_progress",
            )

            self.client.force_login(user)
            response = self.client.post(
                reverse("verification:conduct_surveyor_inspection", args=[task.id]),
                data={
                    "visit_date": "2026-04-18T10:00",
                    "boundary_confirmed": "on",
                    "acreage_confirmed": "on",
                    "price_realistic": "on",
                    "lsb_license_number": surveyor.license_number,
                    "mutation_form": SimpleUploadedFile("mutation.pdf", b"mutation", content_type="application/pdf"),
                    "recommendation": "approve",
                    "notes": "All beacons verified.",
                    "plot_images": [
                        SimpleUploadedFile("plot-1.jpg", b"plotimage", content_type="image/jpeg"),
                    ],
                },
            )

            self.assertRedirects(response, reverse("listings:dashboard_router") + "?section=tasks")
            self.assertTrue(PlotImage.objects.filter(plot=plot, uploaded_by=user).exists())


class OCRExtractionTests(TestCase):
    def test_extract_fields_handles_fixture_layout(self):
        title_deed_text = """
        R E P U B L I C O F K E N YA

        Title Deed
        Ownership certificate for NAIROBI/BLOCK101/45

        OWNER

        KRA PIN

        Registered proprietor

        John Kamau

        PARCEL

        TITLE

        NAIROBI/BLOCK101/45
        """

        official_search_text = """
        R E P U B L I C O F K E N YA

        Official Search Certificate
        Land registry search results for NAIROBI/BLOCK101/45

        OWNER

        KRA PIN

        Registered proprietor

        John Kamau

        PARCEL

        TITLE

        NAIROBI/BLOCK101/45

        Search reference
        number

        SRCH/NAI/2026/0045
        """

        title_fields = DocumentOCRService.extract_fields(title_deed_text)
        search_fields = DocumentOCRService.extract_fields(official_search_text)

        self.assertEqual(title_fields["owner_name"], "John Kamau")
        self.assertEqual(search_fields["owner_name"], "John Kamau")
        self.assertEqual(title_fields["parcel_number"], "NAIROBI/BLOCK101/45")
        self.assertEqual(search_fields["parcel_number"], "NAIROBI/BLOCK101/45")
        self.assertEqual(title_fields["title_number"], "NAIROBI/BLOCK101/45")
        self.assertEqual(search_fields["title_number"], "NAIROBI/BLOCK101/45")
        self.assertEqual(search_fields["search_ref"], "SRCH/NAI/2026/0045")
