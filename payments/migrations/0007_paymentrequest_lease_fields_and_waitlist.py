from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0006_plot_ward_topography_indexes"),
        ("payments", "0006_alter_paymentrequest_category"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentrequest",
            name="good_husbandry_required",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="intended_use",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="lease_security_deposit",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="notice_period_days",
            field=models.PositiveIntegerField(default=90),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="soil_exit_test_required",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="subject_to_sale",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="LeaseWaitlistEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("desired_start_date", models.DateField(blank=True, null=True)),
                ("desired_duration_months", models.PositiveIntegerField(default=12)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("waiting", "Waiting"), ("contacted", "Contacted"), ("confirmed", "Confirmed"), ("converted", "Converted"), ("withdrawn", "Withdrawn")], default="waiting", max_length=20)),
                ("last_notified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("plot", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="lease_waitlist_entries", to="listings.plot")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="lease_waitlist_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["created_at"],
                "unique_together": {("plot", "user")},
            },
        ),
    ]
