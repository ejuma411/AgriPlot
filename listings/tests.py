from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from unittest.mock import patch

from .models import Agent, ContactRequest, Plot
from .verification_service import VerificationService
from .views import _safe_next_url, staff_dashboard, verification_progress


class ListingsRegressionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client(HTTP_HOST="localhost")
        self.user = User.objects.create_user(
            username="agent_user",
            email="agent@example.com",
            password="safe-pass-123",
        )
        self.agent = Agent.objects.create(
            user=self.user,
            phone="0712345678",
            id_number="12345678",
            verified=True,
        )
        self.plot = Plot.objects.create(
            agent=self.agent,
            title="Test Plot",
            location="Nairobi - Westlands",
            area=2.0,
            listing_type="sale",
            land_type="agricultural",
            sale_price="1000000.00",
            price="1000000.00",
            soil_type="Loam",
            crop_suitability="Maize",
        )

    def test_staff_dashboard_renders_for_agent(self):
        request = self.factory.get("/staff-dashboard/")
        request.user = self.user

        response = staff_dashboard(request)

        self.assertEqual(response.status_code, 200)

    def test_verification_progress_handles_single_role_user(self):
        request = self.factory.get("/verification-progress/")
        request.user = self.user

        with patch("listings.views.render", return_value=HttpResponse("ok")) as mocked_render:
            response = verification_progress(request)

        self.assertEqual(response.status_code, 200)
        mocked_render.assert_called_once()

    def test_safe_next_url_rejects_external_redirect(self):
        request = self.factory.get("/register/agent/?next=https://evil.example/phish")

        self.assertEqual(_safe_next_url(request), "/")

    def test_create_verification_tasks_runs_without_initiator(self):
        created_tasks = VerificationService.create_verification_tasks(self.plot)

        self.assertIn("document_review", created_tasks)

    def test_contact_request_allows_null_agent(self):
        contact = ContactRequest.objects.create(
            user=self.user,
            plot=self.plot,
            agent=None,
            request_type="phone_request",
        )

        self.assertIsNone(contact.agent)
        self.assertIn(self.user.username, str(contact))

    def test_register_landowner_page_exists(self):
        response = self.client.get(reverse("listings:register_landowner_simple"))
        self.assertEqual(response.status_code, 302)

    def test_legacy_verify_dashboard_redirects_to_canonical(self):
        response = self.client.get("/verify/dashboard/")
        self.assertEqual(response.status_code, 301)
        self.assertIn(reverse("listings:verification_dashboard"), response["Location"])
