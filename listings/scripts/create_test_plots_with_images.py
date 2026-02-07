# listings/scripts/create_test_plots_with_images.py
import random
from django.core.files.base import ContentFile
from listings.models import Plot, Broker, PlotImage
from django.contrib.auth.models import User
from PIL import Image
from io import BytesIO

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

    for i in range(5):
        plot = Plot.objects.create(
            title=titles[i],
            location=locations[i],
            price=random.randint(1_000_000, 10_000_000),
            area=round(random.uniform(2.0, 6.0), 1),
            soil_type=random.choice(soil_types),
            ph_level=round(random.uniform(5.5, 7.5), 1),
            crop_suitability=crops[i],
            broker=broker
        )

        # Dummy title deed & soil report
        plot.title_deed.save(f"title_deed_{i}.pdf", ContentFile(b"Dummy title deed content"))
        plot.soil_report.save(f"soil_report_{i}.pdf", ContentFile(b"Dummy soil report content"))

        # Generate 3 real dummy images
        for j in range(1, 4):
            # Create image with PIL
            img = Image.new('RGB', (200, 200), color=(random.randint(0,255), random.randint(0,255), random.randint(0,255)))
            buffer = BytesIO()
            img.save(buffer, format='JPEG')
            buffer.seek(0)

            image_file = ContentFile(buffer.read(), name=f"plot_{i}_image_{j}.jpg")
            PlotImage.objects.create(plot=plot, image=image_file)

        print(f"Created plot: {plot.title} with 3 images")
