from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="availability_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="plot",
            name="lease_end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="plot",
            name="lease_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="plot",
            name="market_status",
            field=models.CharField(
                choices=[
                    ("available", "Available"),
                    ("reserved", "Reserved"),
                    ("leased", "Leased"),
                    ("sold", "Sold"),
                ],
                default="available",
                max_length=20,
            ),
        ),
    ]
