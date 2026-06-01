from django.conf import settings
from django.db import migrations, models
from django.db.models import deletion


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankBeneficiary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
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
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=deletion.SET_NULL,
                        related_name="bank_beneficiaries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "payments_bank_beneficiary",
                "ordering": ["legal_name", "bank_name", "account_name"],
            },
        ),
        migrations.CreateModel(
            name="BankTransferRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "provider",
                    models.CharField(
                        choices=[("jenga", "Equity Jenga"), ("manual", "Manual")],
                        default="jenga",
                        max_length=20,
                    ),
                ),
                (
                    "rail",
                    models.CharField(
                        choices=[("pesalink", "PesaLink"), ("rtgs", "RTGS"), ("eft", "EFT")],
                        default="pesalink",
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
                ("reference", models.CharField(blank=True, default="", editable=False, max_length=50, unique=True)),
                ("idempotency_key", models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ("provider_reference", models.CharField(blank=True, max_length=100)),
                ("beneficiary_name", models.CharField(max_length=200)),
                ("bank_name", models.CharField(max_length=100)),
                ("bank_code", models.CharField(blank=True, max_length=20)),
                ("account_name", models.CharField(max_length=200)),
                ("account_number", models.CharField(max_length=50)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15)),
                ("currency", models.CharField(default="KES", max_length=10)),
                ("request_payload", models.JSONField(blank=True, default=dict)),
                ("provider_response", models.JSONField(blank=True, default=dict)),
                ("callback_payload", models.JSONField(blank=True, default=dict)),
                ("failure_reason", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("reconciled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "beneficiary",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=deletion.SET_NULL,
                        related_name="bank_transfer_requests",
                        to="payments.bankbeneficiary",
                    ),
                ),
                (
                    "disbursement",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=deletion.SET_NULL,
                        related_name="bank_transfer_request",
                        to="payments.paymentdisbursement",
                    ),
                ),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=deletion.CASCADE,
                        related_name="bank_transfer_requests",
                        to="payments.paymentrequest",
                    ),
                ),
            ],
            options={
                "db_table": "payments_bank_transfer_request",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="banktransferrequest",
            index=models.Index(fields=["status", "rail"], name="payments_ba_status_e7d6de_idx"),
        ),
        migrations.AddIndex(
            model_name="banktransferrequest",
            index=models.Index(fields=["reference"], name="payments_ba_referen_df5eef_idx"),
        ),
        migrations.AddIndex(
            model_name="banktransferrequest",
            index=models.Index(fields=["provider_reference"], name="payments_ba_provide_34d7ea_idx"),
        ),
        migrations.AddIndex(
            model_name="banktransferrequest",
            index=models.Index(fields=["idempotency_key"], name="payments_ba_idempot_08088f_idx"),
        ),
    ]
