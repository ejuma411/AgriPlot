# Generated manually to match current models

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0007_paymentevent_paymentdispute_paymentmilestone_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankBeneficiary",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bank_beneficiaries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("legal_name", models.CharField(max_length=200)),
                ("bank_name", models.CharField(max_length=100)),
                ("bank_code", models.CharField(blank=True, max_length=20)),
                ("account_name", models.CharField(max_length=200)),
                ("account_number", models.CharField(max_length=50)),
                ("branch_name", models.CharField(blank=True, max_length=100)),
                ("currency", models.CharField(default="KES", max_length=10)),
                ("is_verified", models.BooleanField(default=False)),
                ("verification_reference", models.CharField(blank=True, max_length=120)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "payments_bank_beneficiary",
                "ordering": ["legal_name", "bank_name", "account_name"],
            },
        ),
        migrations.CreateModel(
            name="BankTransferRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("beneficiary_name", models.CharField(max_length=200)),
                ("bank_name", models.CharField(max_length=100)),
                ("bank_code", models.CharField(blank=True, max_length=20)),
                ("account_name", models.CharField(max_length=200)),
                ("account_number", models.CharField(max_length=50)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15)),
                ("currency", models.CharField(default="KES", max_length=10)),
                (
                    "rail",
                    models.CharField(
                        choices=[
                            ("pesalink", "PesaLink"),
                            ("rtgs", "RTGS"),
                            ("eft", "EFT"),
                        ],
                        default="pesalink",
                        max_length=20,
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("jenga", "Equity Jenga"),
                            ("manual", "Manual"),
                        ],
                        default="jenga",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("queued", "Queued"),
                            ("submitted", "Submitted"),
                            ("processing", "Processing"),
                            ("settled", "Settled"),
                            ("failed", "Failed"),
                            ("reversed", "Reversed"),
                            ("reconciled", "Reconciled"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("reference", models.CharField(max_length=50, unique=True, editable=False, default="", blank=True)),
                ("idempotency_key", models.CharField(max_length=100, unique=True, null=True, blank=True)),
                ("provider_reference", models.CharField(max_length=100, blank=True)),
                ("request_payload", models.JSONField(default=dict, blank=True)),
                ("provider_response", models.JSONField(default=dict, blank=True)),
                ("callback_payload", models.JSONField(default=dict, blank=True)),
                ("failure_reason", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(null=True, blank=True)),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("reconciled_at", models.DateTimeField(null=True, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bank_transfer_requests",
                        to="payments.paymentrequest",
                    ),
                ),
                (
                    "disbursement",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bank_transfer_request",
                        to="payments.paymentdisbursement",
                    ),
                ),
                (
                    "beneficiary",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bank_transfer_requests",
                        to="payments.bankbeneficiary",
                    ),
                ),
                (
                    "initiated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="initiated_transfers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "payments_bank_transfer_request",
                "ordering": ["-created_at"],
            },
        ),
    ]