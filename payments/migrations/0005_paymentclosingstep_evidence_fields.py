from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_paymentclosingstep_document"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentclosingstep",
            name="assessed_stamp_duty",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="buyer_confirmed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="consent_reference_number",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="meeting_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="official_market_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="original_title_received",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="seller_confirmed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="seller_id_copy_received",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="paymentclosingstep",
            name="transfer_forms_signed",
            field=models.BooleanField(default=False),
        ),
    ]
