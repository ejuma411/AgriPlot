from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
import json
from requests import ConnectionError as RequestsConnectionError
from unittest.mock import patch

from accounts.models import Profile
from accounts.models import LandownerProfile
from listings.models import Plot
from listings.models import UserInterest
from notifications.models import Notification

from .models import (
    LeaseWaitlistEntry,
    PaymentCertificate,
    PaymentClosingStep,
    PaymentDisbursement,
    PaymentRequest,
)
from .forms import PaymentClosingStepForm, PaymentRequestForm
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
            category=PaymentRequest.Category.COMMITMENT_FEE,
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

    def test_release_keeps_purchase_plot_reserved_until_registration_is_complete(self):
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
        payment.ensure_closing_steps()
        for code in ["agreement", "lcb_consent", "stamp_duty", "completion_docs"]:
            payment.closing_steps.get(code=code).set_status(
                PaymentClosingStep.Status.COMPLETED,
                actor=user,
                bypass_evidence=True,
            )

        payment.apply_transition("release", actor=user)
        plot.refresh_from_db()
        self.assertEqual(plot.market_status, "reserved")
        self.assertIn("Awaiting the statutory closing checklist", plot.availability_notes)

    def test_release_is_blocked_until_required_purchase_closing_steps_are_done(self):
        user = get_user_model().objects.create_user(username="buyer4c", password="secret123")
        landowner = self._create_landowner_for_plot("purchase_owner_c")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Purchase Plot C",
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
        payment.ensure_closing_steps()

        with self.assertRaisesMessage(ValidationError, "Complete these legal steps first"):
            payment.apply_transition("release", actor=user)

    def test_registration_completion_marks_purchase_plot_as_sold(self):
        user = get_user_model().objects.create_user(username="buyer4b", password="secret123")
        landowner = self._create_landowner_for_plot("purchase_owner_b")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Purchase Plot B",
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
            status=PaymentRequest.Status.RELEASED,
        )
        payment.ensure_closing_steps()
        registration_step = payment.closing_steps.get(code="registration")

        registration_step.document = SimpleUploadedFile("new-search.pdf", b"proof")
        registration_step.save(update_fields=["document", "updated_at"])
        registration_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=user)

        plot.refresh_from_db()
        self.assertEqual(plot.market_status, "sold")

    def test_form_calculates_purchase_reservation_amount_from_backend(self):
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
                "phone_number": "254700123456",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["amount"],
            PaymentRequestForm.calculate_amount(
                plot,
                PaymentRequest.TransactionType.PURCHASE,
                PaymentRequest.Category.RESERVATION_DEPOSIT,
            ),
        )

    def test_commitment_fee_is_calculated_from_backend_due_diligence_costs(self):
        landowner = self._create_landowner_for_plot("commitment_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Commitment Plot",
            location="Kisumu",
            area=2.0,
            price="850000.00",
            sale_price="850000.00",
            listing_type="sale",
            land_type="agricultural",
        )

        amount = PaymentRequestForm.calculate_amount(
            plot,
            PaymentRequest.TransactionType.PURCHASE,
            PaymentRequest.Category.COMMITMENT_FEE,
        )

        self.assertEqual(amount, Decimal("4300.00"))

    def test_mpesa_is_blocked_above_fifty_thousand_but_wallet_remains_available(self):
        landowner = self._create_landowner_for_plot("large_payment_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Large Payment Plot",
            location="Nakuru",
            area=4.0,
            price="1200000.00",
            sale_price="1200000.00",
            listing_type="sale",
        )

        mpesa_form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Agreement deposit",
                "description": "Large transaction",
                "amount": "1.00",
                "category": PaymentRequest.Category.AGREEMENT_DEPOSIT,
                "method": PaymentRequest.Method.MPESA_STK,
                "phone_number": "254700123456",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )
        self.assertFalse(mpesa_form.is_valid())
        self.assertIn("method", mpesa_form.errors)
        self.assertIn("bank transfer, card, or wallet", str(mpesa_form.errors["method"]))

        wallet_form = PaymentRequestForm(
            user=None,
            selected_plot=plot,
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "Agreement deposit",
                "description": "Large transaction",
                "amount": "1.00",
                "category": PaymentRequest.Category.AGREEMENT_DEPOSIT,
                "method": PaymentRequest.Method.WALLET,
                "phone_number": "",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )
        self.assertTrue(wallet_form.is_valid(), wallet_form.errors)

    def test_lease_agreement_requires_both_digital_confirmations(self):
        user = get_user_model().objects.create_user(username="lease_buyer", password="secret123")
        seller_user = get_user_model().objects.create_user(username="lease_seller", password="secret123")
        landowner = self._create_landowner_for_plot("lease_terms_owner")
        landowner.user = seller_user
        landowner.save(update_fields=["user"])
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Agreement Plot",
            location="Nakuru",
            area=4.0,
            price="750000.00",
            lease_price_yearly="400000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=user,
            seller=seller_user,
            plot=plot,
            title="Lease request",
            amount="10000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000777",
            lease_start_date="2026-05-01",
            lease_end_date="2027-04-30",
            intended_use="Avocado farming",
        )
        payment.ensure_closing_steps()
        agreement_step = payment.closing_steps.get(code="agreement")

        self.assertFalse(agreement_step.can_mark_complete_with_current_evidence())
        agreement_step.buyer_confirmed_at = timezone.now()
        agreement_step.save(update_fields=["buyer_confirmed_at", "updated_at"])
        self.assertFalse(agreement_step.can_mark_complete_with_current_evidence())
        agreement_step.seller_confirmed_at = timezone.now()
        agreement_step.save(update_fields=["seller_confirmed_at", "updated_at"])
        self.assertTrue(agreement_step.can_mark_complete_with_current_evidence())

    def test_purchase_agreement_form_exposes_role_specific_fields(self):
        buyer = get_user_model().objects.create_user(username="purchase_buyer", password="secret123")
        seller = get_user_model().objects.create_user(username="purchase_seller", password="secret123")
        landowner = self._create_landowner_for_plot("purchase_owner")
        landowner.user = seller
        landowner.save(update_fields=["user"])
        plot = Plot.objects.create(
            landowner=landowner,
            title="Purchase Agreement Plot",
            location="Nakuru",
            area=4.0,
            price="750000.00",
            sale_price="750000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=buyer,
            seller=seller,
            plot=plot,
            title="Purchase request",
            amount="10000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.AGREEMENT_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000888",
        )
        payment.ensure_closing_steps()
        agreement_step = payment.closing_steps.get(code="agreement")

        buyer_form = PaymentClosingStepForm(instance=agreement_step, user=buyer)
        seller_form = PaymentClosingStepForm(instance=agreement_step, user=seller)

        self.assertIn("buyer_accepts_agreement", buyer_form.fields)
        self.assertNotIn("seller_accepts_agreement", buyer_form.fields)
        self.assertNotIn("seller_advocate_name", buyer_form.fields)
        self.assertNotIn("seller_advocate_phone", buyer_form.fields)
        self.assertNotIn("document", buyer_form.fields)

        self.assertIn("seller_accepts_agreement", seller_form.fields)
        self.assertIn("seller_advocate_name", seller_form.fields)
        self.assertIn("seller_advocate_phone", seller_form.fields)
        self.assertIn("document", seller_form.fields)
        self.assertNotIn("buyer_accepts_agreement", seller_form.fields)

    def test_purchase_agreement_requires_document_and_both_confirmations(self):
        buyer = get_user_model().objects.create_user(username="purchase_buyer2", password="secret123")
        seller = get_user_model().objects.create_user(username="purchase_seller2", password="secret123")
        landowner = self._create_landowner_for_plot("purchase_owner2")
        landowner.user = seller
        landowner.save(update_fields=["user"])
        plot = Plot.objects.create(
            landowner=landowner,
            title="Purchase Agreement Plot 2",
            location="Kisumu",
            area=3.5,
            price="900000.00",
            sale_price="900000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=buyer,
            seller=seller,
            plot=plot,
            title="Purchase request",
            amount="15000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.AGREEMENT_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000889",
        )
        payment.ensure_closing_steps()
        agreement_step = payment.closing_steps.get(code="agreement")

        self.assertFalse(agreement_step.can_mark_complete_with_current_evidence())
        agreement_step.document = SimpleUploadedFile("agreement.pdf", b"pdf")
        agreement_step.buyer_confirmed_at = timezone.now()
        self.assertFalse(agreement_step.can_mark_complete_with_current_evidence())
        agreement_step.seller_confirmed_at = timezone.now()
        self.assertTrue(agreement_step.can_mark_complete_with_current_evidence())

    def test_form_forces_mpesa_checkout_and_generates_title(self):
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
                "title": "",
                "description": "",
                "amount": "1.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "method": PaymentRequest.Method.CARD,
                "phone_number": "254700000123",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "on",
                "due_at": "",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)
        self.assertEqual(payment.method, PaymentRequest.Method.MPESA_STK)
        self.assertIn("Reservation Deposit", payment.title)

    def test_transactional_payment_form_rejects_missing_plot(self):
        form = PaymentRequestForm(
            user=None,
            data={
                "plot": "",
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "title": "",
                "description": "",
                "amount": "1.00",
                "category": PaymentRequest.Category.COMMITMENT_FEE,
                "method": PaymentRequest.Method.MPESA_STK,
                "phone_number": "254700000123",
                "lease_start_date": "",
                "lease_end_date": "",
                "escrow_enabled": "",
                "due_at": "",
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("plot", form.errors)

    def test_transactional_payment_model_rejects_missing_plot(self):
        user = get_user_model().objects.create_user(username="buyer_no_plot", password="secret123")
        payment = PaymentRequest(
            buyer=user,
            title="Commitment payment",
            amount="50.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.COMMITMENT_FEE,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PENDING,
            phone_number="254700000321",
        )

        with self.assertRaisesMessage(ValidationError, "A plot is required"):
            payment.full_clean()

    def test_form_limits_choices_to_purchase_and_lease_direct_deals(self):
        form = PaymentRequestForm(user=None)
        self.assertEqual(
            [value for value, _ in form.fields["transaction_type"].choices],
            [PaymentRequest.TransactionType.PURCHASE, PaymentRequest.TransactionType.LEASE],
        )
        self.assertEqual(
            [value for value, _ in form.fields["category"].choices],
            [PaymentRequest.Category.RESERVATION_DEPOSIT, PaymentRequest.Category.ESCROW_DEPOSIT],
        )

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
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
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

    def test_purchase_artifacts_generate_certificates_and_disbursements(self):
        user = get_user_model().objects.create_user(username="artifact_buyer", password="secret123")
        landowner = self._create_landowner_for_plot("artifact_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Artifact Plot",
            location="Narok",
            area=6.0,
            price="3000000.00",
            sale_price="3000000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=user,
            seller=landowner.user,
            plot=plot,
            title="Purchase tracker",
            amount="300000.00",
            method=PaymentRequest.Method.CARD,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.IN_ESCROW,
        )

        payment.ensure_transaction_artifacts()

        self.assertTrue(
            PaymentCertificate.objects.filter(
                payment=payment,
                code="buyer_payment_ack",
                status=PaymentCertificate.Status.ISSUED,
            ).exists()
        )
        self.assertTrue(
            PaymentDisbursement.objects.filter(
                payment=payment,
                code="seller_final_payout",
                recipient_role=PaymentDisbursement.RecipientRole.SELLER,
            ).exists()
        )
        self.assertTrue(
            PaymentDisbursement.objects.filter(
                payment=payment,
                code="platform_escrow_fee",
                recipient_role=PaymentDisbursement.RecipientRole.PLATFORM,
            ).exists()
        )

    def test_purchase_stage_matrix_exposes_forms_and_responsibility(self):
        landowner = self._create_landowner_for_plot("matrix_owner")
        plot = Plot.objects.create(
            landowner=landowner,
            title="Matrix Plot",
            location="Kajiado",
            area=2.0,
            price="1200000.00",
            sale_price="1200000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=get_user_model().objects.create_user(username="matrix_buyer", password="secret123"),
            seller=landowner.user,
            plot=plot,
            title="Matrix tracker",
            amount="120000.00",
            method=PaymentRequest.Method.CARD,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PENDING,
        )

        matrix = payment.transaction_stage_matrix

        self.assertEqual(len(matrix), 6)
        self.assertIn("Official search", matrix[0]["form_document"])
        self.assertIn("Buyer initiates and pays", matrix[0]["who_provides"])
        self.assertIn("digital certified title-copy", matrix[-1]["system_output"].lower())


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

    @override_settings(ENABLE_SMS_NOTIFICATIONS=True)
    @patch("notifications.notification_service.SMSService.send_sms")
    def test_purchase_request_notifies_seller_when_created(self, mock_send_sms):
        owner_user = self.User.objects.create_user(
            username="notify_owner",
            password="secret123",
            email="owner@example.com",
        )
        owner_profile, _ = Profile.objects.get_or_create(
            user=owner_user,
            defaults={"role": "landowner"},
        )
        owner_profile.phone = "0718810503"
        owner_profile.save(update_fields=["phone"])
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
        self.assertRedirects(
            response,
            reverse("payments:detail", kwargs={"pk": payment.pk}),
            fetch_redirect_response=False,
        )
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
        mock_send_sms.assert_called_once()
        self.assertIn("started a purchase payment flow", mock_send_sms.call_args.args[1])

    @override_settings(ENABLE_SMS_NOTIFICATIONS=True)
    @patch("notifications.notification_service.SMSService.send_sms")
    def test_mark_paid_notifies_seller_that_payment_is_confirmed(self, mock_send_sms):
        self.seller.email = "seller@example.com"
        self.seller.save(update_fields=["email"])
        seller_profile = self.seller.profile
        seller_profile.phone = "0718810503"
        seller_profile.save(update_fields=["phone"])
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
        mock_send_sms.assert_called_once()
        self.assertIn("completed payment", mock_send_sms.call_args.args[1])

    def test_finance_dashboard_shows_admin_step_queue(self):
        owner_user = self.User.objects.create_user(
            username="queue_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("queue_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("queue_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Admin Queue Plot",
            location="Kericho",
            area=4.0,
            price="2100000.00",
            sale_price="2100000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Admin Queue Deal",
            amount="210000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000777",
        )
        payment.ensure_closing_steps()
        lcb_step = payment.closing_steps.get(code="lcb_consent")
        lcb_step.status = PaymentClosingStep.Status.IN_PROGRESS
        lcb_step.save(update_fields=["status", "updated_at"])
        self.client.login(username="finance_auth", password="secret123")

        response = self.client.get(reverse("payments:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Steps waiting for AgriPlot admin action")
        self.assertContains(response, "Responsible: Admin / Lawyer")
        self.assertContains(
            response,
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": lcb_step.pk}),
        )

    def test_buyer_cannot_edit_admin_owned_lcb_stage_workspace(self):
        owner_user = self.User.objects.create_user(
            username="lcb_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lcb_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lcb_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="LCB Plot",
            location="Bomet",
            area=3.5,
            price="1800000.00",
            sale_price="1800000.00",
            listing_type="sale",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="LCB Deal",
            amount="180000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000221",
        )
        payment.ensure_closing_steps()
        step = payment.closing_steps.get(code="lcb_consent")
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": step.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin task confirmation")
        self.assertContains(response, "Admin / official action required")
        self.assertNotContains(response, "Save step update")

    def test_completed_lcb_stage_is_not_shown_as_upcoming_in_buyer_workspace(self):
        owner_user = self.User.objects.create_user(
            username="lcb_complete_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lcb_complete_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lcb_complete_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Completed LCB Plot",
            location="Bomet",
            area=3.5,
            price="1800000.00",
            sale_price="1800000.00",
            listing_type="sale",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Completed LCB Deal",
            amount="180000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000222",
        )
        payment.ensure_closing_steps()
        due_diligence_step = payment.closing_steps.get(code="due_diligence")
        agreement_step = payment.closing_steps.get(code="agreement")
        lcb_step = payment.closing_steps.get(code="lcb_consent")
        due_diligence_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.buyer, bypass_evidence=True)
        agreement_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        lcb_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": lcb_step.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Completed")
        self.assertContains(response, "Land Control Board &amp; Family Consents")
        self.assertContains(response, "Open now")
        self.assertContains(response, "Rural Valuation &amp; Stamp Duty")

    def test_security_deposit_workspace_explains_tenant_action_clearly(self):
        owner_user = self.User.objects.create_user(
            username="lease_security_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lease_security_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_security_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Security Plot",
            location="Nakuru",
            area=2.5,
            price="900000.00",
            lease_price_monthly="45000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Lease Security Deal",
            amount="45000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000223",
            lease_start_date=timezone.localdate() + timedelta(days=7),
            lease_end_date=timezone.localdate() + timedelta(days=372),
            lease_security_deposit="90000.00",
        )
        payment.ensure_closing_steps()
        security_step = payment.closing_steps.get(code="payment_security")
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": security_step.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Task confirmation")
        self.assertContains(response, "Only the step currently needed from admin, advocate, buyer, or seller stays open here.")
        self.assertContains(response, "Access control")
        self.assertContains(response, "Signed in as")
        self.assertContains(response, "Buyer / tenant")
        self.assertContains(response, "Confirmation checklist")
        self.assertContains(response, "Pay the deposit through AgriPlot so it is recorded in escrow.")
        self.assertContains(response, "Security deposit checkout form")

    def test_seller_sees_checkout_locked_when_buyer_owns_security_step(self):
        owner_user = self.User.objects.create_user(
            username="lease_security_locked_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lease_security_locked_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_security_locked_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Security Locked Plot",
            location="Nakuru",
            area=2.5,
            price="900000.00",
            lease_price_monthly="45000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Lease Security Locked Deal",
            amount="45000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000229",
            lease_start_date=timezone.localdate() + timedelta(days=7),
            lease_end_date=timezone.localdate() + timedelta(days=372),
            lease_security_deposit="90000.00",
        )
        payment.ensure_closing_steps()
        security_step = payment.closing_steps.get(code="payment_security")
        self.client.login(username="lease_security_locked_owner", password="secret123")

        response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": security_step.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Access control")
        self.assertContains(response, "Seller / landowner")
        self.assertContains(response, "Checkout locked")
        self.assertContains(response, "Only the buyer / tenant can start the security-deposit checkout.")
        self.assertNotContains(response, "Security deposit checkout form")

    def test_workspace_redirects_future_step_back_to_current_open_task(self):
        owner_user = self.User.objects.create_user(
            username="future_step_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("future_step_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("future_step_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Future Step Plot",
            location="Nakuru",
            area=2.0,
            price="1200000.00",
            sale_price="1200000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Future Step Deal",
            amount="120000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000224",
        )
        payment.ensure_closing_steps()
        current_step = payment.closing_steps.get(code="due_diligence")
        future_step = payment.closing_steps.get(code="registration")
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": future_step.pk})
        )

        self.assertRedirects(
            response,
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": current_step.pk}),
            fetch_redirect_response=False,
        )

    def test_invalid_step_update_renders_workspace_with_inline_errors(self):
        owner_user = self.User.objects.create_user(
            username="invalid_update_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("invalid_update_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("invalid_update_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Invalid Update Plot",
            location="Bomet",
            area=3.5,
            price="1800000.00",
            sale_price="1800000.00",
            listing_type="sale",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Invalid Update Deal",
            amount="180000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000231",
        )
        payment.ensure_closing_steps()
        step = payment.closing_steps.get(code="stamp_duty")
        due_diligence_step = payment.closing_steps.get(code="due_diligence")
        agreement_step = payment.closing_steps.get(code="agreement")
        lcb_step = payment.closing_steps.get(code="lcb_consent")
        due_diligence_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.buyer, bypass_evidence=True)
        agreement_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        lcb_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.post(
            reverse("payments:update_closing_step", kwargs={"pk": payment.pk, "step_id": step.pk}),
            data={"status": PaymentClosingStep.Status.COMPLETED, "notes": "Attempting completion too early"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Submission needs correction")
        self.assertContains(response, "Please correct the closing tracker update and try again.")

    def test_denied_step_update_renders_workspace_with_access_control_message(self):
        owner_user = self.User.objects.create_user(
            username="denied_update_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("denied_update_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("denied_update_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Denied Update Plot",
            location="Bomet",
            area=3.5,
            price="1800000.00",
            sale_price="1800000.00",
            listing_type="sale",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Denied Update Deal",
            amount="180000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000232",
        )
        payment.ensure_closing_steps()
        step = payment.closing_steps.get(code="lcb_consent")
        due_diligence_step = payment.closing_steps.get(code="due_diligence")
        agreement_step = payment.closing_steps.get(code="agreement")
        due_diligence_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.buyer, bypass_evidence=True)
        agreement_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.post(
            reverse("payments:update_closing_step", kwargs={"pk": payment.pk, "step_id": step.pk}),
            data={"status": PaymentClosingStep.Status.IN_PROGRESS, "notes": "Buyer trying admin step"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Submission blocked by access control")
        self.assertContains(response, "Access control")

    def test_security_deposit_checkout_uses_exact_agreed_amount(self):
        owner_user = self.User.objects.create_user(
            username="lease_checkout_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lease_checkout_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_checkout_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Checkout Plot",
            location="Nyahururu",
            area=3.0,
            price="1200000.00",
            lease_price_monthly="45000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Lease Deposit Deal",
            amount="45000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.COMMITMENT_FEE,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000224",
            lease_start_date=timezone.localdate() + timedelta(days=10),
            lease_end_date=timezone.localdate() + timedelta(days=375),
            intended_use="Onions",
            lease_security_deposit="125000.00",
        )
        payment.ensure_closing_steps()
        offer_step = payment.closing_steps.get(code="offer")
        lcb_step = payment.closing_steps.get(code="lcb_consent")
        agreement_step = payment.closing_steps.get(code="agreement")
        offer_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.buyer, bypass_evidence=True)
        lcb_step.document = SimpleUploadedFile("lease_lcb.pdf", b"lcb")
        lcb_step.consent_reference_number = "LCB-123"
        lcb_step.meeting_date = timezone.localdate()
        lcb_step.save(update_fields=["document", "consent_reference_number", "meeting_date", "updated_at"])
        lcb_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        agreement_step.buyer_confirmed_at = timezone.now()
        agreement_step.seller_confirmed_at = timezone.now()
        agreement_step.save(update_fields=["buyer_confirmed_at", "seller_confirmed_at", "updated_at"])
        agreement_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        security_step = payment.closing_steps.get(code="payment_security")
        self.client.login(username="buyer_auth", password="secret123")

        workspace_response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": security_step.pk})
        )
        self.assertEqual(workspace_response.status_code, 200)
        self.assertContains(workspace_response, "Security deposit checkout form")
        self.assertContains(workspace_response, "Start checkout")
        self.assertContains(workspace_response, "KES 125,000.00")
        self.assertContains(workspace_response, "M-Pesa number")

        response = self.client.get(
            reverse("payments:create_request"),
            {
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.LEASE,
                "workflow_root_id": payment.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The amount is fixed to the exact agreed deal amount of KES 125,000.00.")
        self.assertContains(response, 'value="125000.00"')

    @override_settings(
        MPESA_CONSUMER_KEY="consumer",
        MPESA_CONSUMER_SECRET="secret",
        MPESA_BUSINESS_SHORTCODE="123456",
        MPESA_PASSKEY="passkey",
        MPESA_ENVIRONMENT="sandbox",
        SITE_URL="http://testserver",
    )
    @patch("payments.views.initiate_stk_push")
    def test_workspace_security_deposit_stk_push_stays_inline_and_saves_on_callback(self, mock_initiate_stk_push):
        mock_initiate_stk_push.return_value = {
            "CheckoutRequestID": "ws-checkout-123",
            "MerchantRequestID": "ws-merchant-456",
            "CustomerMessage": "STK push sent",
            "ResponseDescription": "Success. Request accepted for processing",
        }
        owner_user = self.User.objects.create_user(
            username="lease_inline_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lease_inline_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_inline_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Inline Plot",
            location="Nyeri",
            area=2.8,
            price="950000.00",
            lease_price_monthly="35000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        anchor = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Lease Inline Deal",
            amount="35000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.COMMITMENT_FEE,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000225",
            lease_start_date=timezone.localdate() + timedelta(days=5),
            lease_end_date=timezone.localdate() + timedelta(days=370),
            intended_use="Potatoes",
            lease_security_deposit="87500.00",
        )
        anchor.ensure_closing_steps()
        offer_step = anchor.closing_steps.get(code="offer")
        lcb_step = anchor.closing_steps.get(code="lcb_consent")
        agreement_step = anchor.closing_steps.get(code="agreement")
        offer_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.buyer, bypass_evidence=True)
        lcb_step.document = SimpleUploadedFile("inline_lcb.pdf", b"lcb")
        lcb_step.consent_reference_number = "LCB-456"
        lcb_step.meeting_date = timezone.localdate()
        lcb_step.save(update_fields=["document", "consent_reference_number", "meeting_date", "updated_at"])
        lcb_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        agreement_step.buyer_confirmed_at = timezone.now()
        agreement_step.seller_confirmed_at = timezone.now()
        agreement_step.save(update_fields=["buyer_confirmed_at", "seller_confirmed_at", "updated_at"])
        agreement_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        security_step = anchor.closing_steps.get(code="payment_security")
        self.client.login(username="buyer_auth", password="secret123")

        start_response = self.client.post(
            reverse("payments:closing_step_stk_push", kwargs={"pk": anchor.pk, "step_id": security_step.pk}),
            data={"phone_number": "0718810503"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(start_response.status_code, 200)
        payload = start_response.json()
        self.assertTrue(payload["ok"])
        child_payment = PaymentRequest.objects.get(pk=payload["payment_id"])
        self.assertEqual(child_payment.amount, Decimal("87500.00"))
        self.assertEqual(child_payment.status, PaymentRequest.Status.PENDING)
        self.assertEqual(child_payment.workflow_anchor_payment.pk, anchor.pk)

        poll_response = self.client.get(
            reverse("payments:payment_status_poll", kwargs={"pk": anchor.pk, "payment_id": child_payment.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(poll_response.status_code, 200)
        self.assertEqual(poll_response.json()["state"], "pending")

        callback_payload = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "ws-merchant-456",
                    "CheckoutRequestID": "ws-checkout-123",
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 87500},
                            {"Name": "MpesaReceiptNumber", "Value": "QWE123456"},
                            {"Name": "TransactionDate", "Value": 20260409105500},
                            {"Name": "PhoneNumber", "Value": 254718810503},
                        ]
                    },
                }
            }
        }
        callback_response = self.client.post(
            reverse("payments:daraja_callback"),
            data=json.dumps(callback_payload),
            content_type="application/json",
        )
        self.assertEqual(callback_response.status_code, 200)

        child_payment.refresh_from_db()
        security_step.refresh_from_db()
        self.assertEqual(child_payment.status, PaymentRequest.Status.RELEASED)
        self.assertEqual(security_step.status, PaymentClosingStep.Status.COMPLETED)

        paid_poll_response = self.client.get(
            reverse("payments:payment_status_poll", kwargs={"pk": anchor.pk, "payment_id": child_payment.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(paid_poll_response.status_code, 200)
        self.assertEqual(paid_poll_response.json()["state"], "paid")

    def test_seller_cannot_start_inline_security_deposit_checkout(self):
        owner_user = self.User.objects.create_user(
            username="lease_inline_blocked_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lease_inline_blocked_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_inline_blocked_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Inline Blocked Plot",
            location="Nyeri",
            area=2.8,
            price="950000.00",
            lease_price_monthly="35000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        anchor = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Lease Inline Blocked Deal",
            amount="35000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.COMMITMENT_FEE,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000230",
            lease_start_date=timezone.localdate() + timedelta(days=5),
            lease_end_date=timezone.localdate() + timedelta(days=370),
            intended_use="Potatoes",
            lease_security_deposit="87500.00",
        )
        anchor.ensure_closing_steps()
        offer_step = anchor.closing_steps.get(code="offer")
        lcb_step = anchor.closing_steps.get(code="lcb_consent")
        agreement_step = anchor.closing_steps.get(code="agreement")
        offer_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.buyer, bypass_evidence=True)
        lcb_step.document = SimpleUploadedFile("inline_blocked_lcb.pdf", b"lcb")
        lcb_step.consent_reference_number = "LCB-789"
        lcb_step.meeting_date = timezone.localdate()
        lcb_step.save(update_fields=["document", "consent_reference_number", "meeting_date", "updated_at"])
        lcb_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        agreement_step.buyer_confirmed_at = timezone.now()
        agreement_step.seller_confirmed_at = timezone.now()
        agreement_step.save(update_fields=["buyer_confirmed_at", "seller_confirmed_at", "updated_at"])
        agreement_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=self.finance, bypass_evidence=True)
        security_step = anchor.closing_steps.get(code="payment_security")
        self.client.login(username="lease_inline_blocked_owner", password="secret123")

        response = self.client.post(
            reverse("payments:closing_step_stk_push", kwargs={"pk": anchor.pk, "step_id": security_step.pk}),
            data={"phone_number": "0718810504"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Only the buyer / tenant can start the security-deposit checkout.")

    def test_closing_step_update_resolves_anchor_payment_when_child_pk_is_used(self):
        owner_user = self.User.objects.create_user(
            username="anchor_resolution_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("anchor_resolution_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("anchor_resolution_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Anchor Resolution Plot",
            location="Nakuru",
            area=2.0,
            price="500000.00",
            lease_price_monthly="20000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        anchor = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Anchor Deal",
            amount="20000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.COMMITMENT_FEE,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000226",
            lease_start_date=timezone.localdate(),
            lease_end_date=timezone.localdate() + timedelta(days=365),
            intended_use="Beans",
            lease_security_deposit="40000.00",
        )
        child = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Child Deal",
            amount="40000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.PENDING,
            phone_number="254700000226",
            lease_start_date=anchor.lease_start_date,
            lease_end_date=anchor.lease_end_date,
            intended_use=anchor.intended_use,
            lease_security_deposit=anchor.lease_security_deposit,
            metadata={"workflow_root_id": anchor.pk},
        )
        anchor.ensure_closing_steps()
        step = anchor.closing_steps.get(code="payment_security")
        self.client.login(username="finance_auth", password="secret123")

        response = self.client.post(
            reverse("payments:update_closing_step", kwargs={"pk": child.pk, "step_id": step.pk}),
            data={"status": PaymentClosingStep.Status.IN_PROGRESS, "notes": "Finance follow-up"},
        )

        self.assertEqual(response.status_code, 302)
        step.refresh_from_db()
        self.assertEqual(step.status, PaymentClosingStep.Status.IN_PROGRESS)

    def test_lease_use_land_only_completes_within_approved_date_window(self):
        owner_user = self.User.objects.create_user(
            username="lease_window_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("lease_window_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_window_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Lease Window Plot",
            location="Nyeri",
            area=2.5,
            price="700000.00",
            lease_price_monthly="25000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        future_payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Future Lease Deal",
            amount="25000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.RELEASED,
            phone_number="254700000227",
            lease_start_date=timezone.localdate() + timedelta(days=7),
            lease_end_date=timezone.localdate() + timedelta(days=372),
            intended_use="Maize",
            lease_security_deposit="50000.00",
        )
        future_payment.ensure_closing_steps()
        future_payment.closing_steps.update(status=PaymentClosingStep.Status.COMPLETED)
        future_payment.sync_plot_market_state()
        plot.refresh_from_db()

        self.assertTrue(future_payment.lease_all_steps_completed)
        self.assertTrue(future_payment.lease_ready_for_use)
        self.assertFalse(future_payment.lease_currently_active)
        self.assertEqual(future_payment.transfer_status_label, "Approved - awaiting start date")
        self.assertEqual(plot.market_status, "reserved")
        self.assertFalse(plot.has_active_lease)
        self.assertEqual(future_payment.dashboard_process_steps[-1]["status"], "current")

        active_plot = Plot.objects.create(
            landowner=landowner,
            title="Active Lease Plot",
            location="Meru",
            area=3.0,
            price="800000.00",
            lease_price_monthly="30000.00",
            listing_type="lease",
            land_type="agricultural",
        )
        active_payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=active_plot,
            title="Active Lease Deal",
            amount="30000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.RELEASED,
            phone_number="254700000228",
            lease_start_date=timezone.localdate() - timedelta(days=3),
            lease_end_date=timezone.localdate() + timedelta(days=362),
            intended_use="Avocado",
            lease_security_deposit="60000.00",
        )
        active_payment.ensure_closing_steps()
        active_payment.closing_steps.update(status=PaymentClosingStep.Status.COMPLETED)
        active_payment.sync_plot_market_state()
        active_plot.refresh_from_db()

        self.assertTrue(active_payment.lease_currently_active)
        self.assertEqual(active_payment.transfer_status_label, "Lease active")
        self.assertEqual(active_plot.market_status, "leased")
        self.assertTrue(active_plot.has_active_lease)
        self.assertEqual(active_payment.dashboard_process_steps[-1]["status"], "completed")

    def test_staff_dashboard_shows_payment_admin_tasks(self):
        self.finance.is_staff = True
        self.finance.save(update_fields=["is_staff"])
        owner_user = self.User.objects.create_user(
            username="staff_queue_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("staff_queue_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("staff_queue_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Staff Queue Plot",
            location="Nakuru",
            area=4.0,
            price="2200000.00",
            sale_price="2200000.00",
            listing_type="sale",
            land_type="agricultural",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Staff Queue Deal",
            amount="220000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000331",
        )
        payment.ensure_closing_steps()
        step = payment.closing_steps.get(code="lcb_consent")
        step.status = PaymentClosingStep.Status.IN_PROGRESS
        step.save(update_fields=["status", "updated_at"])
        self.client.login(username="finance_auth", password="secret123")

        response = self.client.get(reverse("listings:dashboard_router") + "?section=finance")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escrow &amp; Payout Control")
        self.assertContains(response, "Escrow &amp; Payouts")
        self.assertContains(
            response,
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": step.pk}),
        )

    @override_settings(
        MPESA_CONSUMER_KEY="consumer",
        MPESA_CONSUMER_SECRET="secret",
        MPESA_BUSINESS_SHORTCODE="123456",
        MPESA_PASSKEY="passkey",
        MPESA_ENVIRONMENT="sandbox",
        SITE_URL="http://testserver",
    )
    @patch("payments.daraja.requests.request")
    def test_create_request_handles_daraja_connection_failure(self, mock_request):
        owner_user = self.User.objects.create_user(
            username="daraja_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("daraja_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("daraja_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Daraja Plot",
            location="Nakuru",
            area=2,
            price="450000.00",
            sale_price="450000.00",
            listing_type="sale",
        )
        mock_request.side_effect = RequestsConnectionError("remote closed")
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.post(
            reverse("payments:create_request"),
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "amount": "10.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "phone_number": "254700123456",
                "lease_start_date": "",
                "lease_end_date": "",
            },
            follow=True,
        )

        payment = PaymentRequest.objects.latest("created_at")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payment.metadata.get("provider_start_status"),
            "pending_provider_confirmation",
        )
        self.assertTrue(payment.events.filter(event_type="provider_confirmation_pending").exists())

    @override_settings(
        MPESA_CONSUMER_KEY="consumer",
        MPESA_CONSUMER_SECRET="secret",
        MPESA_BUSINESS_SHORTCODE="123456",
        MPESA_PASSKEY="passkey",
        MPESA_ENVIRONMENT="sandbox",
        SITE_URL="http://testserver",
    )
    @patch("payments.daraja.requests.request")
    def test_create_request_marks_timeout_as_pending_provider_confirmation(self, mock_request):
        owner_user = self.User.objects.create_user(
            username="daraja_timeout_owner",
            password="secret123",
        )
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("daraja_timeout_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("daraja_timeout_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Daraja Timeout Plot",
            location="Nakuru",
            area=2,
            price="450000.00",
            sale_price="450000.00",
            listing_type="sale",
        )
        mock_request.side_effect = RequestsConnectionError("remote closed")
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.post(
            reverse("payments:create_request"),
            data={
                "plot": plot.pk,
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "amount": "10.00",
                "category": PaymentRequest.Category.RESERVATION_DEPOSIT,
                "phone_number": "254700123456",
                "lease_start_date": "",
                "lease_end_date": "",
            },
            follow=True,
        )

        payment = PaymentRequest.objects.latest("created_at")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payment.metadata.get("provider_start_status"), "pending_provider_confirmation")
        self.assertTrue(
            payment.events.filter(event_type="provider_confirmation_pending").exists()
        )

    def test_create_request_rejects_transactional_payment_without_plot(self):
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.post(
            reverse("payments:create_request"),
            data={
                "plot": "",
                "transaction_type": PaymentRequest.TransactionType.PURCHASE,
                "amount": "50.00",
                "category": PaymentRequest.Category.COMMITMENT_FEE,
                "phone_number": "254700123456",
                "lease_start_date": "",
                "lease_end_date": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a plot before creating commitment")
        self.assertFalse(
            PaymentRequest.objects.filter(
                buyer=self.buyer,
                category=PaymentRequest.Category.COMMITMENT_FEE,
            ).exists()
        )

    def test_buyer_can_open_dispute(self):
        self.client.login(username="buyer_auth", password="secret123")
        response = self.client.post(
            reverse("payments:open_dispute", kwargs={"pk": self.payment.pk}),
            {"reason": "refund_request", "details": "Seller missed the agreed next step."},
        )

        self.assertRedirects(response, reverse("payments:detail", kwargs={"pk": self.payment.pk}))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentRequest.Status.DISPUTED)

    def test_detail_view_shows_clearing_house_sections(self):
        owner_user = self.User.objects.create_user(username="detail_owner", password="secret123")
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("detail_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("detail_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Detail Plot",
            location="Nyandarua",
            area=5,
            price="1500000.00",
            sale_price="1500000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Detail Purchase",
            amount="150000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000888",
        )
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(reverse("payments:detail", kwargs={"pk": payment.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Clearing-House Process")
        self.assertContains(response, "Clearance Evidence")
        self.assertContains(response, "Payout Waterfall")
        self.assertContains(response, "Officer Payments")
        self.assertContains(response, "AgriPlot Revenue")

    def test_closing_step_workspace_loads_without_missing_url_reverses(self):
        owner_user = self.User.objects.create_user(username="workspace_owner", password="secret123")
        Profile.objects.get_or_create(user=owner_user, defaults={"role": "landowner"})
        landowner = LandownerProfile.objects.create(
            user=owner_user,
            national_id=SimpleUploadedFile("workspace_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("workspace_pin.txt", b"pin"),
        )
        plot = Plot.objects.create(
            landowner=landowner,
            title="Workspace Plot",
            location="Laikipia",
            area=3,
            price="1800000.00",
            sale_price="1800000.00",
            listing_type="sale",
        )
        payment = PaymentRequest.objects.create(
            buyer=self.buyer,
            seller=owner_user,
            plot=plot,
            title="Workspace Purchase",
            amount="180000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.PAID,
            phone_number="254700000889",
        )
        payment.ensure_closing_steps()
        step = payment.closing_steps.order_by("sequence").first()
        self.client.login(username="buyer_auth", password="secret123")

        response = self.client.get(
            reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": step.pk})
        )

        self.assertEqual(response.status_code, 200)


class LeaseLifecycleTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.tenant = self.User.objects.create_user(
            username="lease_tenant",
            password="secret123",
            email="tenant@example.com",
        )
        self.seller = self.User.objects.create_user(
            username="lease_landowner",
            password="secret123",
            email="landowner@example.com",
        )
        self.waiting_user = self.User.objects.create_user(
            username="next_tenant",
            password="secret123",
            email="next@example.com",
        )
        tenant_profile, _ = Profile.objects.get_or_create(user=self.tenant, defaults={"role": "buyer"})
        tenant_profile.phone = "0718810503"
        tenant_profile.save(update_fields=["phone"])
        seller_profile, _ = Profile.objects.get_or_create(user=self.seller, defaults={"role": "landowner"})
        seller_profile.phone = "0718810504"
        seller_profile.save(update_fields=["phone"])
        waiting_profile, _ = Profile.objects.get_or_create(user=self.waiting_user, defaults={"role": "buyer"})
        waiting_profile.phone = "0718810505"
        waiting_profile.save(update_fields=["phone"])
        self.landowner = LandownerProfile.objects.create(
            user=self.seller,
            national_id=SimpleUploadedFile("lease_owner_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("lease_owner_pin.txt", b"pin"),
        )

    def test_lifecycle_command_contacts_next_waitlist_user_at_notice_window(self):
        today = timezone.localdate()
        plot = Plot.objects.create(
            landowner=self.landowner,
            title="Notice Plot",
            location="Njoro",
            area=3.0,
            price="600000.00",
            lease_price_yearly="300000.00",
            listing_type="lease",
            land_type="agricultural",
            market_status="leased",
            lease_start_date=today - timedelta(days=180),
            lease_end_date=today + timedelta(days=90),
        )
        payment = PaymentRequest.objects.create(
            buyer=self.tenant,
            seller=self.seller,
            plot=plot,
            title="Active lease",
            amount="10000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.RELEASED,
            phone_number="254700001111",
            lease_start_date=today - timedelta(days=180),
            lease_end_date=today + timedelta(days=90),
            intended_use="Onions",
            notice_period_days=90,
        )
        LeaseWaitlistEntry.objects.create(plot=plot, user=self.waiting_user)

        call_command("process_lease_lifecycle")

        waitlist_entry = LeaseWaitlistEntry.objects.get(plot=plot, user=self.waiting_user)
        payment.refresh_from_db()
        self.assertEqual(waitlist_entry.status, LeaseWaitlistEntry.Status.CONTACTED)
        self.assertTrue(payment.metadata.get("waitlist_notice_sent_at"))
        self.assertTrue(
            Notification.objects.filter(
                user=self.waiting_user,
                title__icontains="Confirm your next lease interest",
            ).exists()
        )

    @override_settings(ENABLE_SMS_NOTIFICATIONS=True)
    @patch("notifications.notification_service.TextSMSService.send_sms")
    def test_lifecycle_command_sends_renewal_warning_to_current_tenant(self, mock_send_sms):
        today = timezone.localdate()
        plot = Plot.objects.create(
            landowner=self.landowner,
            title="Renewal Plot",
            location="Njoro",
            area=3.0,
            price="600000.00",
            lease_price_yearly="300000.00",
            listing_type="lease",
            land_type="agricultural",
            market_status="leased",
            lease_start_date=today - timedelta(days=180),
            lease_end_date=today + timedelta(days=90),
        )
        payment = PaymentRequest.objects.create(
            buyer=self.tenant,
            seller=self.seller,
            plot=plot,
            title="Renewal lease",
            amount="10000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.RELEASED,
            phone_number="254700001111",
            lease_start_date=today - timedelta(days=180),
            lease_end_date=today + timedelta(days=90),
            intended_use="Onions",
            notice_period_days=90,
        )

        call_command("process_lease_lifecycle")

        payment.refresh_from_db()
        self.assertEqual(
            sorted(payment.metadata.get("tenant_renewal_reminder_buckets", []), reverse=True),
            [90],
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.tenant,
                title__icontains="renewal window is now open",
                message__icontains="terminate the tenancy",
            ).exists()
        )
        self.assertGreaterEqual(mock_send_sms.call_count, 2)

    def test_lifecycle_command_does_not_repeat_same_renewal_bucket(self):
        today = timezone.localdate()
        plot = Plot.objects.create(
            landowner=self.landowner,
            title="Renewal Plot 2",
            location="Njoro",
            area=3.0,
            price="600000.00",
            lease_price_yearly="300000.00",
            listing_type="lease",
            land_type="agricultural",
            market_status="leased",
            lease_start_date=today - timedelta(days=180),
            lease_end_date=today + timedelta(days=90),
        )
        payment = PaymentRequest.objects.create(
            buyer=self.tenant,
            seller=self.seller,
            plot=plot,
            title="Renewal lease",
            amount="10000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.RELEASED,
            phone_number="254700001111",
            lease_start_date=today - timedelta(days=180),
            lease_end_date=today + timedelta(days=90),
            intended_use="Onions",
            notice_period_days=90,
        )

        call_command("process_lease_lifecycle")
        first_count = Notification.objects.filter(
            user=self.tenant,
            title__icontains="renewal window is now open",
        ).count()

        call_command("process_lease_lifecycle")
        second_count = Notification.objects.filter(
            user=self.tenant,
            title__icontains="renewal window is now open",
        ).count()

        payment.refresh_from_db()
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        self.assertEqual(payment.metadata.get("tenant_renewal_reminder_buckets", []), [90])

    def test_lifecycle_command_releases_expired_lease_and_notifies_waitlist(self):
        today = timezone.localdate()
        plot = Plot.objects.create(
            landowner=self.landowner,
            title="Expired Plot",
            location="Njoro",
            area=3.0,
            price="600000.00",
            lease_price_yearly="300000.00",
            listing_type="lease",
            land_type="agricultural",
            market_status="leased",
            lease_start_date=today - timedelta(days=365),
            lease_end_date=today - timedelta(days=1),
        )
        payment = PaymentRequest.objects.create(
            buyer=self.tenant,
            seller=self.seller,
            plot=plot,
            title="Expired active lease",
            amount="10000.00",
            method=PaymentRequest.Method.MPESA_STK,
            category=PaymentRequest.Category.ESCROW_DEPOSIT,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status=PaymentRequest.Status.RELEASED,
            phone_number="254700001111",
            lease_start_date=today - timedelta(days=365),
            lease_end_date=today - timedelta(days=1),
            intended_use="Onions",
            notice_period_days=90,
        )
        waitlist_entry = LeaseWaitlistEntry.objects.create(
            plot=plot,
            user=self.waiting_user,
            status=LeaseWaitlistEntry.Status.CONFIRMED,
        )

        call_command("process_lease_lifecycle")

        plot.refresh_from_db()
        payment.refresh_from_db()
        waitlist_entry.refresh_from_db()
        self.assertEqual(plot.market_status, "available")
        self.assertIsNone(plot.lease_end_date)
        self.assertTrue(payment.metadata.get("lease_release_processed_at"))
        self.assertIsNotNone(waitlist_entry.last_notified_at)
        self.assertTrue(
            Notification.objects.filter(
                user=self.waiting_user,
                title__icontains="Land is now free to lease",
            ).exists()
        )


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
