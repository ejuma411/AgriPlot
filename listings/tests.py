from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from unittest.mock import patch

from accounts.models import Profile
from .models import Agent, ContactRequest, FraudReport, Plot, UserInterest, UserPlotView
from .recommendation import RecommendationService
from payments.models import LeaseWaitlistEntry
from verification.models import VerificationStatus
from verification.verification_service import VerificationService
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
        self.buyer = User.objects.create_user(
            username="buyer_user",
            email="buyer@example.com",
            password="safe-pass-456",
        )
        Profile.objects.update_or_create(user=self.buyer, defaults={"role": "buyer", "intent": "buyer"})
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
        VerificationStatus.objects.create(
            content_type=ContentType.objects.get_for_model(Plot),
            object_id=self.plot.id,
            current_stage="approved",
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
        self.assertIn(reverse("verification:verification_dashboard"), response["Location"])

    def test_home_keeps_reserved_plots_visible_with_status(self):
        reserved_plot = Plot.objects.create(
            agent=self.agent,
            title="Reserved Plot",
            location="Nakuru - Njoro",
            county="Nakuru",
            subcounty="Njoro",
            area=3.0,
            listing_type="sale",
            land_type="agricultural",
            sale_price="800000.00",
            price="800000.00",
            market_status="reserved",
            soil_type="Red Volcanic",
        )
        VerificationStatus.objects.create(
            content_type=ContentType.objects.get_for_model(Plot),
            object_id=reserved_plot.id,
            current_stage="approved",
        )

        response = self.client.get(reverse("listings:home"))

        self.assertEqual(response.status_code, 200)
        plot_ids = [plot.id for plot in response.context["featured_plots"]]
        self.assertIn(self.plot.id, plot_ids)
        self.assertIn(reserved_plot.id, plot_ids)
        self.assertEqual(reserved_plot.market_status, "reserved")

    def test_home_natural_language_query_maps_to_location_area_price_and_listing_type(self):
        lease_plot = Plot.objects.create(
            agent=self.agent,
            title="Njoro Lease Farm",
            location="Nakuru - Njoro",
            county="Nakuru",
            subcounty="Njoro",
            area=3.0,
            listing_type="lease",
            land_type="agricultural",
            lease_price_yearly="900000.00",
            price="900000.00",
            market_status="available",
            soil_type="Red Volcanic",
        )
        VerificationStatus.objects.create(
            content_type=ContentType.objects.get_for_model(Plot),
            object_id=lease_plot.id,
            current_stage="approved",
        )

        response = self.client.get(
            reverse("listings:home"),
            {"q": "3 acres for lease in Njoro under 1M"},
        )

        self.assertEqual(response.status_code, 200)
        plot_ids = [plot.id for plot in response.context["featured_plots"]]
        self.assertIn(lease_plot.id, plot_ids)
        self.assertNotIn(self.plot.id, plot_ids)

    def test_hybrid_leased_plot_stays_purchase_open(self):
        hybrid_plot = Plot.objects.create(
            agent=self.agent,
            title="Hybrid Lease Sale Plot",
            location="Nakuru - Molo",
            county="Nakuru",
            subcounty="Molo",
            area=4.0,
            listing_type="both",
            land_type="agricultural",
            sale_price="1500000.00",
            lease_price_yearly="500000.00",
            price="1500000.00",
            market_status="leased",
            lease_start_date="2026-01-01",
            lease_end_date="2026-12-31",
        )

        self.assertTrue(hybrid_plot.has_active_lease)
        self.assertTrue(hybrid_plot.purchase_checkout_open)
        self.assertFalse(hybrid_plot.lease_checkout_open)
        self.assertEqual(hybrid_plot.occupancy_status_label, "Leased - Still for Sale")

    def test_join_lease_waitlist_creates_entry(self):
        leased_plot = Plot.objects.create(
            agent=self.agent,
            title="Occupied Lease Plot",
            location="Nakuru - Njoro",
            county="Nakuru",
            subcounty="Njoro",
            area=3.0,
            listing_type="lease",
            land_type="agricultural",
            lease_price_yearly="700000.00",
            price="700000.00",
            market_status="leased",
            lease_start_date="2026-01-01",
            lease_end_date="2026-12-31",
        )

        self.client.force_login(self.user)
        response = self.client.post(reverse("listings:join_lease_waitlist", args=[leased_plot.id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            LeaseWaitlistEntry.objects.filter(plot=leased_plot, user=self.user).exists()
        )

    def test_contacted_waitlist_user_can_confirm_interest(self):
        leased_plot = Plot.objects.create(
            agent=self.agent,
            title="Occupied Lease Plot",
            location="Nakuru - Njoro",
            county="Nakuru",
            subcounty="Njoro",
            area=3.0,
            listing_type="lease",
            land_type="agricultural",
            lease_price_yearly="700000.00",
            price="700000.00",
            market_status="leased",
            lease_start_date="2026-01-01",
            lease_end_date="2026-12-31",
        )
        entry = LeaseWaitlistEntry.objects.create(
            plot=leased_plot,
            user=self.user,
            status=LeaseWaitlistEntry.Status.CONTACTED,
        )

        self.client.force_login(self.user)
        response = self.client.post(reverse("listings:confirm_lease_waitlist", args=[leased_plot.id]))

        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.status, LeaseWaitlistEntry.Status.CONFIRMED)

    def test_home_keeps_leased_plots_visible_for_next_lease_booking(self):
        leased_plot = Plot.objects.create(
            agent=self.agent,
            title="Occupied Lease Plot",
            location="Nakuru - Njoro",
            county="Nakuru",
            subcounty="Njoro",
            area=3.0,
            listing_type="lease",
            land_type="agricultural",
            lease_price_yearly="700000.00",
            price="700000.00",
            market_status="leased",
            lease_start_date="2026-01-01",
            lease_end_date="2026-12-31",
        )
        VerificationStatus.objects.create(
            content_type=ContentType.objects.get_for_model(Plot),
            object_id=leased_plot.id,
            current_stage="approved",
        )

        response = self.client.get(reverse("listings:home"))

        self.assertEqual(response.status_code, 200)
        plot_ids = [plot.id for plot in response.context["featured_plots"]]
        self.assertIn(leased_plot.id, plot_ids)
        self.assertContains(response, "Reserve Next Lease")

    def test_plot_absolute_url_uses_slug_route(self):
        url = self.plot.get_absolute_url()
        self.assertIn(f"/{self.plot.id}/", url)
        self.assertIn("test-plot", url)

    def test_recommendation_service_prefers_sale_for_buyer_intent(self):
        sale_plot = Plot.objects.create(
            agent=self.agent,
            title="Buyer Match Plot",
            location="Nakuru - Elementaita",
            county="Nakuru",
            area=5.0,
            listing_type="sale",
            land_type="agricultural",
            sale_price="2100000.00",
            price="2100000.00",
        )
        lease_plot = Plot.objects.create(
            agent=self.agent,
            title="Lease Match Plot",
            location="Nakuru - Gilgil",
            county="Nakuru",
            area=5.0,
            listing_type="lease",
            land_type="agricultural",
            lease_price_yearly="300000.00",
            price="300000.00",
        )
        UserInterest.objects.create(user=self.buyer, plot=self.plot)

        results = list(RecommendationService().recommend_for_user(self.buyer, limit=5))

        self.assertIn(sale_plot, results)
        self.assertNotIn(lease_plot, results)

    def test_submit_fraud_report_creates_report(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("listings:submit_fraud_report", args=[self.plot.id]),
            {"reason": "Title details look inconsistent", "notes": "Please verify."},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(FraudReport.objects.filter(plot=self.plot, reporter=self.buyer).exists())

    def test_plot_detail_records_authenticated_view_event(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("listings:plot_detail", args=[self.plot.id]))

        self.assertEqual(response.status_code, 200)
        view_event = UserPlotView.objects.get(user=self.buyer, plot=self.plot)
        self.assertEqual(view_event.view_count, 1)

    def test_home_keeps_reserved_lease_plots_visible_for_next_lease_booking(self):
        reserved_lease_plot = Plot.objects.create(
            agent=self.agent,
            title="Reserved Lease Plot",
            location="Nakuru - Njoro",
            county="Nakuru",
            subcounty="Njoro",
            area=3.0,
            listing_type="lease",
            land_type="agricultural",
            lease_price_yearly="700000.00",
            price="700000.00",
            market_status="reserved",
            lease_start_date="2026-06-01",
            lease_end_date="2027-05-31",
        )
        VerificationStatus.objects.create(
            content_type=ContentType.objects.get_for_model(Plot),
            object_id=reserved_lease_plot.id,
            current_stage="approved",
        )

        response = self.client.get(reverse("listings:home"))

        self.assertEqual(response.status_code, 200)
        plot_ids = [plot.id for plot in response.context["featured_plots"]]
        self.assertIn(reserved_lease_plot.id, plot_ids)
        self.assertContains(response, "Reserve Next Lease")
