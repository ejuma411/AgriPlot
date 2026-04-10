from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0005_remove_marketpriceband_listings_ma_county_9348d1_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="topography",
            field=models.CharField(
                blank=True,
                choices=[
                    ("flat", "Flat"),
                    ("gentle_slope", "Gentle Slope"),
                    ("sloped", "Sloped"),
                    ("hilly", "Hilly"),
                    ("valley", "Valley Bottom"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="plot",
            name="ward",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddIndex(
            model_name="plot",
            index=models.Index(fields=["county", "subcounty", "ward"], name="listings_pl_county__cfd8ef_idx"),
        ),
    ]
