from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0008_alter_verificationdocument_doc_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="search_certificate_date",
            field=models.DateField(blank=True, help_text="Official search certificate date", null=True),
        ),
        migrations.AddField(
            model_name="plot",
            name="search_reference_number",
            field=models.CharField(blank=True, help_text="Official search reference number", max_length=100),
        ),
        migrations.AddField(
            model_name="extensionreport",
            name="soil_ph",
            field=models.DecimalField(blank=True, decimal_places=2, help_text="Measured soil pH", max_digits=4, null=True),
        ),
        migrations.AddField(
            model_name="extensionreport",
            name="topography",
            field=models.CharField(blank=True, choices=[("flat", "Flat"), ("gentle", "Gentle Slope"), ("steep", "Steep")], max_length=20),
        ),
        migrations.AddField(
            model_name="extensionreport",
            name="current_land_use",
            field=models.TextField(blank=True, help_text="Current land use on site"),
        ),
        migrations.AddField(
            model_name="extensionreport",
            name="lcb_zone",
            field=models.BooleanField(default=False, help_text="Subject to Land Control Board (LCB) consent"),
        ),
        migrations.AddField(
            model_name="surveyorreport",
            name="mutation_form",
            field=models.FileField(blank=True, help_text="Certified copy of the latest mutation form/survey plan", null=True, upload_to="documents/mutation_forms/"),
        ),
        migrations.AddField(
            model_name="surveyorreport",
            name="lsb_license_number",
            field=models.CharField(blank=True, help_text="Land Surveyors Board (LSB) registration number", max_length=100),
        ),
        migrations.AlterField(
            model_name="surveyorreport",
            name="ground_acreage",
            field=models.DecimalField(blank=True, decimal_places=4, help_text="Measured area on ground (hectares)", max_digits=10, null=True),
        ),
    ]
