from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0013_switch_assigned_counties_to_arrayfield"),
    ]

    operations = [
        migrations.AddField(
            model_name="verificationtask",
            name="review_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
