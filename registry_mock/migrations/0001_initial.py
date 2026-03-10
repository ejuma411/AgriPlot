from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MockLandRegistry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("parcel_number", models.CharField(db_index=True, max_length=100, unique=True)),
                ("registered_owner_name", models.CharField(max_length=255)),
                ("owner_id_number", models.CharField(max_length=20)),
                ("owner_kra_pin", models.CharField(blank=True, max_length=20)),
                ("acreage_ha", models.DecimalField(decimal_places=4, max_digits=10)),
                ("land_type", models.CharField(choices=[("FREEHOLD", "Freehold"), ("LEASEHOLD", "Leasehold")], max_length=20)),
                ("is_charged", models.BooleanField(default=False)),
                ("has_caution", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["parcel_number"], name="registry_moc_parcel__9a0c45_idx"),
                    models.Index(fields=["registered_owner_name"], name="registry_moc_registe_fa1c0c_idx"),
                ],
            },
        ),
    ]
