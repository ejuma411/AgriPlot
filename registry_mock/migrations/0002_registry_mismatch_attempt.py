from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("registry_mock", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RegistryMismatchAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("parcel_number", models.CharField(db_index=True, max_length=100)),
                ("provided_owner_name", models.CharField(blank=True, max_length=255)),
                ("provided_owner_id", models.CharField(blank=True, max_length=50)),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="auth.user",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["parcel_number", "created_at"], name="registry_moc_parcel__0d3c4e_idx"),
                ],
            },
        ),
    ]
