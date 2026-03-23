from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("listings", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="KES", max_length=10)),
                ("category", models.CharField(choices=[("viewing_fee", "Viewing Fee"), ("reservation_deposit", "Reservation Deposit"), ("verification_package", "Verification Package"), ("escrow_deposit", "Escrow Deposit"), ("service_fee", "Service Fee")], default="viewing_fee", max_length=40)),
                ("method", models.CharField(choices=[("mpesa_stk", "M-Pesa STK Push"), ("mpesa_paybill", "M-Pesa Paybill / Till"), ("card", "Card"), ("bank_transfer", "Bank Transfer"), ("airtel_money", "Airtel Money"), ("wallet", "AgriPlot Wallet"), ("manual_escrow", "Manual Escrow")], default="mpesa_stk", max_length=40)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("pending", "Pending Payment"), ("paid", "Paid"), ("in_escrow", "In Escrow"), ("partially_released", "Partially Released"), ("released", "Released"), ("refunded", "Refunded"), ("disputed", "Disputed"), ("cancelled", "Cancelled"), ("failed", "Failed")], default="draft", max_length=30)),
                ("phone_number", models.CharField(blank=True, max_length=20)),
                ("escrow_enabled", models.BooleanField(default=True)),
                ("provider_reference", models.CharField(blank=True, max_length=120)),
                ("internal_reference", models.CharField(editable=False, max_length=24, unique=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("buyer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payment_requests_as_buyer", to=settings.AUTH_USER_MODEL)),
                ("plot", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payment_requests", to="listings.plot")),
                ("seller", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payment_requests_as_seller", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PaymentEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=40)),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payment_events", to=settings.AUTH_USER_MODEL)),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="payments.paymentrequest")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PaymentDispute",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(choices=[("seller_no_show", "Seller No-show"), ("missing_documents", "Missing Documents"), ("payment_not_recognized", "Payment Not Recognized"), ("fraud_signal", "Fraud Signal"), ("refund_request", "Refund Request"), ("other", "Other")], max_length=40)),
                ("details", models.TextField()),
                ("status", models.CharField(choices=[("open", "Open"), ("under_review", "Under Review"), ("resolved", "Resolved"), ("rejected", "Rejected")], default="open", max_length=20)),
                ("resolution_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("opened_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payment_disputes_opened", to=settings.AUTH_USER_MODEL)),
                ("payment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="dispute", to="payments.paymentrequest")),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payment_disputes_resolved", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PaymentMilestone",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("sequence", models.PositiveIntegerField(default=1)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("submitted", "Submitted"), ("approved", "Approved"), ("released", "Released"), ("refunded", "Refunded"), ("blocked", "Blocked")], default="pending", max_length=20)),
                ("evidence_notes", models.TextField(blank=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="milestones", to="payments.paymentrequest")),
            ],
            options={"ordering": ["sequence", "created_at"], "unique_together": {("payment", "sequence")}},
        ),
    ]
