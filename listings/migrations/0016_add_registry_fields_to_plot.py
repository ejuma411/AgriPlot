from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0015_merge_0014_review_metadata_and_verification_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="is_subdivision",
            field=models.BooleanField(default=False, help_text="True when listing is for a portion of a larger parcel"),
        ),
        migrations.AddField(
            model_name="plot",
            name="original_parcel_number",
            field=models.CharField(
                blank=True,
                help_text="Original parcel number when listing a subdivision",
                max_length=100,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="plot",
            name="registry_owner_name",
            field=models.CharField(blank=True, help_text="Owner name fetched from registry", max_length=255),
        ),
        migrations.AddField(
            model_name="plot",
            name="registry_owner_id_number",
            field=models.CharField(blank=True, help_text="Owner ID fetched from registry", max_length=50),
        ),
        migrations.AddField(
            model_name="plot",
            name="registry_owner_kra_pin",
            field=models.CharField(blank=True, help_text="Owner KRA PIN fetched from registry", max_length=50),
        ),
        migrations.AddField(
            model_name="plot",
            name="registry_area_ha",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="Area (hectares) fetched from registry",
                max_digits=12,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="plot",
            name="registry_land_type",
            field=models.CharField(blank=True, help_text="Title type fetched from registry (FREEHOLD/LEASEHOLD)", max_length=20),
        ),
        migrations.AddField(
            model_name="plot",
            name="registry_has_encumbrances",
            field=models.BooleanField(default=False, help_text="Encumbrance status fetched from registry"),
        ),
    ]
