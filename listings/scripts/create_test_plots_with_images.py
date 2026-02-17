# listings/scripts/create_test_plots_with_images.py
# NOTE: Plot images removed in favour of GIS (latitude/longitude). This script now creates plots with coordinates.
import random
from django.core.files.base import ContentFile
from listings.models import Plot, Broker
from django.contrib.auth.models import User

# Get broker 'admin'
try:
    admin_user = User.objects.get(username='Admin')
    broker = Broker.objects.get(user=admin_user)
except (User.DoesNotExist, Broker.DoesNotExist):
    print("Broker admin does not exist or has no Broker object.")
    broker = None

if broker:
    titles = [
        "5-Acre Fertile Farm in Kitale",
        "3-Acre Organic Land in Eldoret",
        "2-Acre Hillside Plot in Nakuru",
        "4-Acre Irrigated Farm in Narok",
        "6-Acre Mixed-Crop Land in Thika"
    ]
    locations = [
        "Kitale, Trans-Nzoia",
        "Eldoret, Uasin Gishu",
        "Nakuru, Nakuru County",
        "Narok, Narok County",
        "Thika, Kiambu County"
    ]
    soil_types = ['Loam', 'Clay', 'Sandy', 'Silty', 'Peaty']
    crops = ['Maize, Beans', 'Wheat, Barley', 'Tomatoes, Onions', 'Sugarcane', 'Bananas, Coffee']
    # Sample coordinates (Kenya)
    coords = [(0.9947, 34.5994), (-0.5143, 35.2698), (-0.3031, 36.0800), (-1.0833, 35.8667), (-1.0333, 37.0694)]

    for i in range(5):
        lat, lon = coords[i]
        plot = Plot.objects.create(
            title=titles[i],
            location=locations[i],
            price=random.randint(1_000_000, 10_000_000),
            area=round(random.uniform(2.0, 6.0), 1),
            soil_type=random.choice(soil_types),
            ph_level=round(random.uniform(5.5, 7.5), 1),
            crop_suitability=crops[i],
            agent=broker,
            latitude=lat,
            longitude=lon,
        )

        try:
            plot.title_deed.save(f"title_deed_{i}.pdf", ContentFile(b"Dummy title deed content"), save=False)
            plot.soil_report.save(f"soil_report_{i}.pdf", ContentFile(b"Dummy soil report content"), save=False)
        except Exception:
            pass
        plot.save()
        print(f"Created plot: {plot.title} with coordinates ({lat}, {lon})")
