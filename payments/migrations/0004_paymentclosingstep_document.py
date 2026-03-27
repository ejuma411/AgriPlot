from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_paymentclosingstep"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentclosingstep",
            name="document",
            field=models.FileField(blank=True, null=True, upload_to="payments/closing_docs/"),
        ),
    ]
