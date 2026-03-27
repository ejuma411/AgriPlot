from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0003_plot_other_amenities"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="market_zone",
            field=models.CharField(
                choices=[
                    ("rural", "Rural"),
                    ("peri_urban", "Peri-Urban"),
                    ("urban", "Urban"),
                ],
                default="rural",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="plot",
            name="price_review_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="plot",
            name="pricing_override_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="marketpriceband",
            name="area_unit",
            field=models.CharField(
                choices=[("acres", "Acres"), ("hectares", "Hectares")],
                default="acres",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="marketpriceband",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="marketpriceband",
            name="market_zone",
            field=models.CharField(
                choices=[
                    ("rural", "Rural"),
                    ("peri_urban", "Peri-Urban"),
                    ("urban", "Urban"),
                ],
                default="rural",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="marketpriceband",
            name="source",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="marketpriceband",
            name="subcounty",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.RenameField(
            model_name="marketpriceband",
            old_name="min_price_per_acre",
            new_name="min_price_per_unit",
        ),
        migrations.RenameField(
            model_name="marketpriceband",
            old_name="max_price_per_acre",
            new_name="max_price_per_unit",
        ),
    ]
