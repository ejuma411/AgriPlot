import os
import sys

# Add project root to Python path
sys.path.append('/home/new/Documents/PROJECTS/AgriPlot')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agriplot.settings')

import django
from django.conf import settings

# Disable logging so we don't get read-only file system errors
os.environ['DJANGO_SETTINGS_MODULE'] = 'agriplot.settings'
try:
    import agriplot.settings
    agriplot.settings.LOGGING_CONFIG = None
except:
    pass

django.setup()

from transactions.models import Transaction

# Find a completed transaction
transaction = Transaction.objects.filter(stage='completed').first()

if transaction:
    print(f"Triggering final completion email and report for Transaction ID: {transaction.id}...")
    try:
        transaction._send_transaction_reports()
        print("✅ Successfully sent completion emails with PDF attached!")
    except Exception as e:
        print(f"❌ Error while sending: {e}")
else:
    print("No completed transactions found in the database. Trying to find any transaction to simulate...")
    # fallback to any transaction if no completed ones
    t = Transaction.objects.first()
    if t:
        print(f"Using Transaction ID: {t.id} instead.")
        t._send_transaction_reports()
        print("✅ Successfully sent completion emails with PDF attached!")
    else:
        print("No transactions found at all.")
