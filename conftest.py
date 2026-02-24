# conftest.py
import os
import django
from django.conf import settings

# Set up Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agriplot.settings')
django.setup()