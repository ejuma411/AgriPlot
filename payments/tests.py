from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from .forms import PaymentRequestForm
from .models import PaymentRequest


class PaymentRequestFormTests(SimpleTestCase):
    def test_start_workflow_only_does_not_require_amount_or_category(self):
        plot = SimpleNamespace(
            id=51,
            title="Green Acres 051",
            listing_type="sale",
            land_type="agricultural",
            sale_price=Decimal("2500000.00"),
        )
        user = SimpleNamespace(
            is_authenticated=True,
            username="buyer",
            profile=SimpleNamespace(phone="254712345678"),
        )

        form = PaymentRequestForm(
            data={"transaction_type": PaymentRequest.TransactionType.PURCHASE},
            user=user,
            selected_plot=plot,
            start_workflow_only=True,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(form.cleaned_data["plot"], plot)
        self.assertEqual(
            form.cleaned_data["category"],
            PaymentRequest.Category.AGREEMENT_DEPOSIT,
        )
        self.assertEqual(form.cleaned_data["amount"], Decimal("0.00"))
