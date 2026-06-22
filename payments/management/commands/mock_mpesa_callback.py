import json
import logging
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.test import RequestFactory

from payments.views_mpesa_callback import mpesa_wallet_callback
from payments.models import PaymentRequest

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Mocks a successful M-Pesa STK Push callback for local testing of Escrow flows."

    def add_arguments(self, parser):
        parser.add_argument("checkout_request_id", type=str, help="The Daraja CheckoutRequestID to mock (e.g. ws_CO_120620261100)")
        parser.add_argument("--amount", type=str, default="1000", help="The amount paid (default 1000)")
        parser.add_argument("--receipt", type=str, help="The M-Pesa receipt number (randomly generated if omitted)")
        parser.add_argument("--phone", type=str, default="254700000000", help="The payer's phone number")

    def handle(self, *args, **options):
        checkout_request_id = options["checkout_request_id"]
        amount = options["amount"]
        receipt = options["receipt"] or f"MK{uuid.uuid4().hex[:8].upper()}"
        phone = options["phone"]

        # Build mock payload matching Safaricom structure
        payload = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": f"29115-34620561-1",
                    "CheckoutRequestID": checkout_request_id,
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {
                                "Name": "Amount",
                                "Value": float(amount)
                            },
                            {
                                "Name": "MpesaReceiptNumber",
                                "Value": receipt
                            },
                            {
                                "Name": "Balance"
                            },
                            {
                                "Name": "TransactionDate",
                                "Value": 20260622110000
                            },
                            {
                                "Name": "PhoneNumber",
                                "Value": int(phone)
                            }
                        ]
                    }
                }
            }
        }

        self.stdout.write(self.style.WARNING(f"Sending Mock M-Pesa STK Push..."))
        self.stdout.write(f"CheckoutRequestID: {checkout_request_id}")
        self.stdout.write(f"Amount: KES {amount}")
        self.stdout.write(f"Receipt: {receipt}")

        # Ensure the payment actually exists and is pending
        payment = PaymentRequest.objects.filter(provider_reference=checkout_request_id).first()
        if not payment:
            payment = PaymentRequest.objects.filter(metadata__daraja_checkout_request_id=checkout_request_id).first()
            
        if payment:
            self.stdout.write(self.style.SUCCESS(f"Found matching PaymentRequest: {payment.internal_reference}"))
        else:
            self.stdout.write(self.style.ERROR(f"WARNING: Could not find any PaymentRequest matching checkout ID '{checkout_request_id}'"))

        # Create mock HTTP request
        factory = RequestFactory()
        request = factory.post('/payments/api/mpesa/callback/', 
                             data=json.dumps(payload),
                             content_type='application/json')
        
        # Invoke the view directly
        response = mpesa_wallet_callback(request)
        
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("--- Mock Callback Processed ---"))
        self.stdout.write(f"Response Status: {response.status_code}")
        self.stdout.write(f"Response Body: {response.content.decode('utf-8')}")
        
        if payment:
            # Refresh from db to show updated status
            payment.refresh_from_db()
            self.stdout.write(self.style.SUCCESS(f"Payment Status is now: {payment.status}"))
            if payment.status == 'paid':
                self.stdout.write(self.style.SUCCESS("Escrow logic triggered successfully!"))
