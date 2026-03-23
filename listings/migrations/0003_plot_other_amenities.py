from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0002_plot_market_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="plot",
            name="other_amenities",
            field=models.TextField(blank=True),
        ),
    ]
