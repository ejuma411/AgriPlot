from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentrequest",
            name="lease_end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="lease_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="transaction_type",
            field=models.CharField(
                choices=[
                    ("purchase", "Purchase"),
                    ("lease", "Lease"),
                    ("service", "Service"),
                ],
                default="service",
                max_length=20,
            ),
        ),
    ]
