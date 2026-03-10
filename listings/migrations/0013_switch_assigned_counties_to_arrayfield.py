from django.db import migrations, models
import django.contrib.postgres.fields


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0012_merge_0011_add_owner_kra_pin_number_0011_alter_surveyorreport_beacon_status"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                ALTER TABLE listings_extensionofficer
                ADD COLUMN assigned_counties_array varchar(100)[];
                """,
                """
                UPDATE listings_extensionofficer
                SET assigned_counties_array = COALESCE(
                    (SELECT array_agg(value) FROM jsonb_array_elements_text(assigned_counties) AS value),
                    ARRAY[]::varchar(100)[]
                );
                """,
                """
                ALTER TABLE listings_extensionofficer
                DROP COLUMN assigned_counties;
                """,
                """
                ALTER TABLE listings_extensionofficer
                RENAME COLUMN assigned_counties_array TO assigned_counties;
                """,
                """
                ALTER TABLE listings_landsurveyor
                ADD COLUMN assigned_counties_array varchar(100)[];
                """,
                """
                UPDATE listings_landsurveyor
                SET assigned_counties_array = COALESCE(
                    (SELECT array_agg(value) FROM jsonb_array_elements_text(assigned_counties) AS value),
                    ARRAY[]::varchar(100)[]
                );
                """,
                """
                ALTER TABLE listings_landsurveyor
                DROP COLUMN assigned_counties;
                """,
                """
                ALTER TABLE listings_landsurveyor
                RENAME COLUMN assigned_counties_array TO assigned_counties;
                """,
            ],
            reverse_sql=[
                """
                ALTER TABLE listings_extensionofficer
                ADD COLUMN assigned_counties_jsonb jsonb;
                """,
                """
                UPDATE listings_extensionofficer
                SET assigned_counties_jsonb = to_jsonb(assigned_counties);
                """,
                """
                ALTER TABLE listings_extensionofficer
                DROP COLUMN assigned_counties;
                """,
                """
                ALTER TABLE listings_extensionofficer
                RENAME COLUMN assigned_counties_jsonb TO assigned_counties;
                """,
                """
                ALTER TABLE listings_landsurveyor
                ADD COLUMN assigned_counties_jsonb jsonb;
                """,
                """
                UPDATE listings_landsurveyor
                SET assigned_counties_jsonb = to_jsonb(assigned_counties);
                """,
                """
                ALTER TABLE listings_landsurveyor
                DROP COLUMN assigned_counties;
                """,
                """
                ALTER TABLE listings_landsurveyor
                RENAME COLUMN assigned_counties_jsonb TO assigned_counties;
                """,
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="extensionofficer",
                    name="assigned_counties",
                    field=django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=100),
                        blank=True,
                        default=list,
                        size=None,
                        help_text="List of counties they can verify",
                    ),
                ),
                migrations.AlterField(
                    model_name="landsurveyor",
                    name="assigned_counties",
                    field=django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=100),
                        blank=True,
                        default=list,
                        size=None,
                        help_text="List of counties they can verify",
                    ),
                ),
            ],
        ),
    ]
