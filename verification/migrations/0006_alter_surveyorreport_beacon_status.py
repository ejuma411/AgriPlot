from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("verification", "0005_officer_and_surveyor_evidence_uploads"),
    ]

    operations = [
        migrations.AlterField(
            model_name="surveyorreport",
            name="beacon_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("all_present_and_intact", "All beacons present and intact"),
                    ("beacons_missing", "Some beacons missing (re-establishment required)"),
                    ("displaced", "Beacons displaced or tampered with"),
                    ("boundary_dispute", "Boundary dispute noted with adjacent plots"),
                ],
                max_length=50,
            ),
        ),
    ]
