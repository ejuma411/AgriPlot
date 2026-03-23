from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("verification", "0002_alter_verificationstatus_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="verificationtask",
            name="benefit_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="verificationtask",
            name="benefit_currency",
            field=models.CharField(default="KES", max_length=10),
        ),
        migrations.AddField(
            model_name="verificationtask",
            name="benefit_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="verificationtask",
            name="benefit_recorded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="verificationtask",
            name="benefit_status",
            field=models.CharField(
                choices=[
                    ("not_applicable", "Not Applicable"),
                    ("pending", "Pending"),
                    ("earned", "Earned"),
                    ("paid", "Paid"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
