from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0009_add_professional_verification_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="extensionreport",
            name="soil_classification",
            field=models.CharField(blank=True, help_text="e.g., Black Cotton, Red Volcanic", max_length=50),
        ),
        migrations.AddField(
            model_name="extensionreport",
            name="power_access",
            field=models.CharField(choices=[("grid", "Grid Power"), ("offgrid", "Off-grid / Solar"), ("none", "No Power"), ("unknown", "Unknown")], default="unknown", max_length=50),
        ),
        migrations.AddField(
            model_name="surveyorreport",
            name="deed_area",
            field=models.DecimalField(blank=True, decimal_places=4, help_text="Area as stated on title deed (hectares)", max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="surveyorreport",
            name="encroachment_found",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="surveyorreport",
            name="encroachment_details",
            field=models.TextField(blank=True),
        ),
    ]
