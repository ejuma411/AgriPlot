import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agriplot.settings')
django.setup()

tables = [
    'listings_watersource',
    'listings_road',
    'listings_market',
    'listings_school',
    'listings_healthfacility'
]

with connection.cursor() as cursor:
    for table in tables:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN latitude numeric(9, 6);")
            print(f"Added latitude to {table}")
        except Exception as e:
            pass

        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN longitude numeric(9, 6);")
            print(f"Added longitude to {table}")
        except Exception as e:
            pass

        try:
            cursor.execute(f"ALTER TABLE {table} DROP COLUMN location;")
            print(f"Dropped location from {table}")
        except Exception as e:
            pass

    try:
        cursor.execute("ALTER TABLE listings_plot DROP COLUMN geom;")
        print("Dropped geom from listings_plot")
    except Exception as e:
        pass

print("Done patching local DB!")
