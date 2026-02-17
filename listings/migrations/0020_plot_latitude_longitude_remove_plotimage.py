# Replace plot images with GIS (latitude/longitude)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0019_pricecomparable_landownerprofile_rejection_reason_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Latitude (e.g. -1.292066 for Nairobi)",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="plot",
            name="longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Longitude (e.g. 36.821946 for Nairobi)",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="plot",
            index=models.Index(fields=["latitude", "longitude"], name="listings_pl_latitud_7c2e0d_idx"),
        ),
        migrations.DeleteModel(
            name="PlotImage",
        ),
    ]
