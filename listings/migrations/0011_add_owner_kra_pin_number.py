from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0010_add_full_alignment_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="owner_kra_pin_number",
            field=models.CharField(blank=True, help_text="KRA PIN number of the registered owner", max_length=20),
        ),
    ]
