from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("verification", "0004_extensionreport_distance_to_market_m_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="extensionreport",
            name="soil_analysis_report",
            field=models.FileField(
                blank=True,
                help_text="Official soil analysis report from the field or lab.",
                null=True,
                upload_to="documents/soil_analysis_reports/",
            ),
        ),
        migrations.AddField(
            model_name="surveyorreport",
            name="signed_survey_plan",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="documents/signed_survey_plans/",
            ),
        ),
    ]
