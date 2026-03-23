from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.core import mail
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Profile
from accounts.models import LandownerProfile
from listings.models import Plot
from listings.models import UserInterest
from notifications.models import Notification

from .models import PaymentRequest
from .forms import PaymentRequestForm
from .permissions import FINANCE_ADMIN_GROUP


class PaymentFlowOverviewTests(SimpleTestCase):
    def test_payment_flow_page_loads(self):
        response = self.client.get(reverse("payments:flow_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AgriPlot payment flow")

    def test_dashboard_page_loads(self):
        response = self.client.get(reverse("payments:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AgriPlot payments")


class PaymentRequestModelTests(TestCase):
    def _create_landowner_for_plot(self, username):
        user = get_user_model().objects.create_user(username=username, password="secret123")
        Profile.objects.get_or_create(user=user, defaults={"role": "landowner"})
        return LandownerProfile.objects.create(
            user=user,
            national_id=SimpleUploadedFile(f"{username}_id.txt", b"id"),
            kra_pin=SimpleUploadedFile(f"{username}_pin.txt", b"pin"),
        )

    def test_reference_is_generated(self):
        user = get_user_model().objects.create_user(
            username="buyer1",
            password="secret123",
        )
        payment = PaymentRequest.objects.create(
            buyer=user,
            title="Viewing fee",
            amount="2500.00",
            method=PaymentRequest.Method.CARD,
            category=PaymentRequest.Category.VIEWING_FEE,
        )

        self.assertTrue(payment.internal_reference.startswith("AGP-"))

    def test_payment_transition_rules_block_invalid_release_from_pending(self):
        user = get_user_model().objects.create_user(username="buyer2", password="secret123")
        payment = PaymentRequest.objects.create(
            buyer=user,
            title="Reservation deposit",
            amount="10000.00",
            method=PaymentRequest.Method.CARD,
            category=PaymentRequest.Category.RESERVATION_DEPOSIT,
            status=PaymentRequest.Status.PENDING,
        )

        with self.assertRaisesMessage(ValidationError, "not allowed"):
            payment.apply_transition("release", actor=user)

    def test_lease_checkout_is_blocked_when_plot_is_already_leased_for_that_period(self):
        user = get_user_model().objects.create_user(username="buyer3", password="secret123")
        landowner = self._create_landowner_for_plot("lease_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Leased Plot",
            location="Nyeri",
            area=3.0,
            price="900000.00",
            lease_price_monthly="45000.00",
            listing_type="lease",
            market_status="leased",
            lease_start_date="2026-04-01",
            lease_end_date="2026-10-01",
        )
        payment = PaymentRequest(
            buyer=user,
            plot=plot,
            title="Lease deposit",
            amount="30000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            lease_start_date="2026-05-01",
            lease_end_date="2026-06-01",
            phone_number="254700000111",
        )

        with self.assertRaisesMessage(ValidationError, "already leased"):
            payment.full_clean()

    def test_release_marks_plot_as_sold_for_purchase(self):
        user = get_user_model().objects.create_user(username="buyer4", password="secret123")
        landowner = self._create_landowner_for_plot("purchase_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Purchase Plot",
            location="Naivasha",
            area=5.0,
            price="2500000.00",
            sale_price="2500000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=user,
            plot=plot,
            title="Purchase deposit",
            amount="500000.00",
            method=PaymentRequest.Method.CARD,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.IN_ESCROW,
        )

        payment.apply_transition("release", actor=user)
        plot.refresh_from_db()
        self.assertEqual(plot.market_status, "sold")

    def test_form_calculates_purchase_reservation_deposit_from_plot_price(self):
        landowner = self._create_landowner_for_plot("amount_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Amount Plot",
            location="Machakos",
            area=1.5,
            price="1000000.00",
            sale_price="1000000.00",
            listing_type="sale",
        )

        form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Reservation",
                "description": "Reserve this plot",
                "amount": "1.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "method": PaymentRequest.Method.CARD,
                "phone_number": "",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amount"], PaymentRequestForm.normalize_amount("50000.00"))

    def test_form_saves_method_specific_metadata(self):
        landowner = self._create_landowner_for_plot("meta_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Metadata Plot",
            location="Kisumu",
            area=2.5,
            price="850000.00",
            sale_price="850000.00",
            listing_type="sale",
        )

        form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Card payment",
                "description": "Card checkout",
                "amount": "1.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "method": PaymentRequest.Method.CARD,
                "phone_number": "",
                "cardholder_name": "Buyer One",
                "card_last4": "4242",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)
        self.assertEqual(payment.metadata["cardholder_name"], "Buyer One")
        self.assertEqual(payment.metadata["card_last4"], "4242")

    def test_mobile_push_methods_only_need_phone_number(self):
        landowner = self._create_landowner_for_plot("mobile_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Mobile Plot",
            location="Kiambu",
            area=2.0,
            price="900000.00",
            sale_price="900000.00",
            listing_type="sale",
        )

        mpesa_form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "M-Pesa checkout",
                "description": "Prompt buyer phone",
                "amount": "1.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "method": PaymentRequest.Method.MPESA_STK,
                "phone_number": "254700111222",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )
        airtel_form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Airtel checkout",
                "description": "Prompt buyer phone",
                "amount": "1.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "method": PaymentRequest.Method.AIRTEL_MONEY,
                "phone_number": "254733111222",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        self.assertTrue(mpesa_form.is_valid(), mpesa_form.errors)
        self.assertTrue(airtel_form.is_valid(), airtel_form.errors)

    def test_form_sets_due_at_automatically_for_non_finance_user(self):
        landowner = self._create_landowner_for_plot("deadline_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Deadline Plot",
            location="Meru",
            area=1.8,
            price="700000.00",
            sale_price="700000.00",
            listing_type="sale",
        )

        form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Viewing fee",
                "description": "Auto deadline test",
                "amount": "1.00",
                "category": PaymentRequest.Category.VIEWING_FEE,
                "method": PaymentRequest.Method.MPESA_STK,
                "phone_number": "254700111999",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.cleaned_data["due_at"])


class PaymentAuthorizationTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.buyer = self.User.objects.create_user(username="buyer_auth", password="secret123")
        self.seller = self.User.objects.create_user(username="seller_auth", password="secret123")
        self.finance = self.User.objects.create_user(username="finance_auth", password="secret123")
        Profile.objects.get_or_create(user=self.buyer, defaults={"role": "buyer"})
        Profile.objects.get_or_create(user=self.seller, defaults={"role": "landowner"})
        Profile.objects.get_or_create(user=self.finance, defaults={"role": "admin"})
        group, _ = Group.objects.get_or_create(name=FINANCE_ADMIN_GROUP)
        self.finance.groups.add(group)
        self.payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            title="Escrow deposit",
            amount="50000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            status=PaymentRequest.Status.PENDING,
            phone_number="254700000000",
        )

    def test_create_request_prefills_plot_from_querystring(self):
        prefill_owner_user = self.User.objects.create_user(
            username="prefill_owner", password="secret123"
        )
        Profile.objects.get_or_create(user=prefill_owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=prefill_owner_user,
            national_id=SimpleUploadedFile("prefill_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("prefill_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Demo Plot",
            location="Nakuru",
            area=4.5,
            price="750000.00",
            sale_price="750000.00",
        )
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(f"{reverse('payments:create_request')}?plot={plot.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Starting from plot:")
        self.assertEqual(response.context["form"].fields["plot"].initial, plot)

    def test_buyer_cannot_release_payment(self):
        self.client.login(username="buyer_auth", password="secret123")
        response = self.client.post(
            reverse("payments:transition", kwargs={"pk": self.payment.pk, "action": "release"})
        )

        self.assertRedirects(response, reverse("payments:detail", kwargs={"pk": self.payment.pk}))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentRequest.Status.PENDING)

    def test_finance_admin_can_mark_paid(self):
        self.client.login(username="finance_auth", password="secret123")
        response = self.client.post(
            reverse("payments:transition", kwargs={"pk": self.payment.pk, "action": "mark_paid"})
        )

        self.assertRedirects(response, reverse("payments:detail", kwargs={"pk": self.payment.pk}))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentRequest.Status.PAID)

    def test_purchase_request_notifies_seller_when_created(self):
        owner_user = self.User.objects.create_user(
            username="notify_owner",
            password="secret123",
            email="owner@example.com",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("notify_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("notify_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Transparency Plot",
            location="Eldoret",
            area=3.2,
            price="1200000.00",
            sale_price="1200000.00",
            listing_type="sale",
        )
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.post(
            reverse("payments:create_request"),
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Reservation deposit",
                "description": "Buyer wants to proceed",
                "amount": "1.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "method": PaymentRequest.Method.MPESA_STK,
                "phone_number": "254700123456",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        payment = PaymentRequest.objects.latest("created_at")
        self.assertRedirects(response, reverse("payments:detail", kwargs={"pk": payment.pk}))
        self.assertTrue(
            Notification.objects.filter(
                user=owner_user,
                plot=plot,
                title__icontains="Buyer initiated purchase",
            ).exists()
        )
        interest = UserInterest.objects.get(user=self.buyer, plot=plot)
        self.assertIn("Buyer initiated a purchase flow through checkout", interest.message)
        self.assertTrue(any("Buyer initiated Purchase" in email.subject for email in mail.outbox))

    def test_mark_paid_notifies_seller_that_payment_is_confirmed(self):
        self.seller.email = "seller@example.com"
        self.seller.save(update_fields=["email"])
        self.client.login(username="finance_auth", password="secret123")

        response = self.client.post(
            reverse("payments:transition", kwargs={"pk": self.payment.pk, "action": "mark_paid"})
        )

        self.assertRedirects(response, reverse("payments:detail", kwargs={"pk": self.payment.pk}))
        self.assertTrue(
            Notification.objects.filter(
                user=self.seller,
                title__icontains="payment confirmed",
            ).exists()
        )
        self.assertTrue(any("Payment confirmed" in email.subject for email in mail.outbox))

    def test_buyer_can_open_dispute(self):
        self.client.login(username="buyer_auth", password="secret123")
        response = self.client.post(
            reverse("payments:open_dispute", kwargs={"pk": self.payment.pk}),
            {"reason": "refund_request", "details": "Seller missed the agreed next step."},
        )

        self.assertRedirects(response, reverse("payments:detail", kwargs={"pk": self.payment.pk}))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentRequest.Status.DISPUTED)


class SavedPlotFlowTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.buyer = self.User.objects.create_user(username="buyer_save", password="secret123")
        self.landowner_user = self.User.objects.create_user(username="seller_save", password="secret123")
        Profile.objects.get_or_create(user=self.buyer, defaults={"role": "buyer"})
        Profile.objects.get_or_create(user=self.landowner_user, defaults={"role": "landowner"})
        self.landowner = LandownerProfile.objects.create(
            user=self.landowner_user,
            national_id=SimpleUploadedFile("id.txt", b"id"),
            kra_pin=SimpleUploadedFile("pin.txt", b"pin"),
        )
        self.plot = Plot.objects.create(
            landowner=self.landowner,
            title="Shortlist Plot",
            location="Eldoret",
            area=2.0,
            price="1200000.00",
            sale_price="1200000.00",
        )

    def test_buyer_can_save_and_unsave_plot(self):
        self.client.login(username="buyer_save", password="secret123")

        response = self.client.post(
            reverse("listings:toggle_saved_plot", kwargs={"plot_id": self.plot.pk}),
            {"next": reverse("listings:plot_detail", kwargs={"id": self.plot.pk})},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("listings:plot_detail", kwargs={"id": self.plot.pk}),
        )
        self.assertTrue(self.buyer.plot_interests.filter(plot=self.plot).exists())

        response = self.client.post(
            reverse("listings:toggle_saved_plot", kwargs={"plot_id": self.plot.pk}),
            {"next": reverse("listings:plot_detail", kwargs={"id": self.plot.pk})},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("listings:plot_detail", kwargs={"id": self.plot.pk}),
        )
        self.assertFalse(self.buyer.plot_interests.filter(plot=self.plot).exists())
