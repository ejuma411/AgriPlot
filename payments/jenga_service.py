"""
Jenga API Integration Service
Handles C2B, B2C, and B2B payments with webhook verification
"""

import json
import logging
import hashlib
import hmac
import base64
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


class JengaError(Exception):
    """Custom exception for Jenga API errors"""
    pass


class JengaService:
    """Service for Jenga API integration"""
    
    def __init__(self):
        self.base_url = settings.JENGA_API_BASE_URL
        self.api_key = settings.JENGA_API_KEY
        self.api_secret = settings.JENGA_API_SECRET
        self.merchant_code = settings.JENGA_MERCHANT_CODE
        self.environment = settings.JENGA_ENVIRONMENT
        self.webhook_secret = settings.JENGA_WEBHOOK_SECRET
        
        # Corporate account details
        self.corporate_account = {
            'account_number': settings.JENGA_CORPORATE_ACCOUNT_NUMBER,
            'account_name': settings.JENGA_CORPORATE_ACCOUNT_NAME,
            'bank_code': settings.JENGA_CORPORATE_BANK_CODE,
        }
    
    def _get_access_token(self):
        """
        Get OAuth2 access token from Jenga.
        Tokens are cached to avoid rate limiting.
        """
        cache_key = 'jenga_access_token'
        token = cache.get(cache_key)
        
        if token:
            return token
        
        try:
            # Generate basic auth
            credentials = f"{self.api_key}:{self.api_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                f"{self.base_url}/authentication/api/v3/oauth/token",
                headers=headers,
                json={
                    'grant_type': 'client_credentials',
                    'merchant_code': self.merchant_code
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                token = data.get('access_token')
                expires_in = data.get('expires_in', 3600)
                cache.set(cache_key, token, timeout=expires_in - 300)  # Cache for 5 min less
                return token
            else:
                logger.error(f"Failed to get Jenga token: {response.text}")
                raise JengaError(f"Authentication failed: {response.status_code}")
                
        except Exception as e:
            logger.exception("Jenga token acquisition failed")
            raise JengaError(f"Token acquisition error: {str(e)}")
    
    def _get_headers(self):
        """Get common headers for Jenga API requests"""
        return {
            'Authorization': f'Bearer {self._get_access_token()}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Merchant-Code': self.merchant_code
        }
    
   #  def _generate_signature(self, payload):
   #      """
   #      Generate HMAC-SHA256 signature for webhook verification.
   #      This ensures the webhook is genuinely from Jenga.
   #      """
   #      message = json.dumps(payload, sort_keys=True)
   #      signature = hmac.new(
   #          self.webhook_secret.encode('utf-8'),
   #          message.encode('utf-8'),
   #          hashlib.sha256
   #      ).hexdigest()
   #      return signature
    
   #  def verify_webhook_signature(self, payload, received_signature):
   #      """
   #      Verify that the webhook signature matches.
   #      Returns True if signature is valid.
   #      """
   #      expected_signature = self._generate_signature(payload)
   #      return hmac.compare_digest(expected_signature, received_signature)
    
    # ============================================================
    # C2B (Customer to Business) - Deposits
    # ============================================================
    
    def initiate_c2b_checkout(self, amount, phone_number, reference, customer_name=None, email=None):
        """
        Initiate a C2B payment via Jenga Checkout.
        Customer pays from their bank app or mobile money.
        
        Args:
            amount: Payment amount (Decimal)
            phone_number: Customer's phone number
            reference: Unique transaction reference
            customer_name: Optional customer name
            email: Optional customer email
            
        Returns:
            dict: Checkout response containing checkout_url and checkout_id
        """
        try:
            headers = self._get_headers()
            
            payload = {
                'merchantCode': self.merchant_code,
                'amount': str(float(amount)),
                'currencyCode': 'KES',
                'reference': reference,
                'customerPhoneNumber': phone_number,
                'customerName': customer_name or '',
                'customerEmail': email or '',
                'callbackUrl': settings.JENGA_WEBHOOK_C2B_URL,
                'redirectUrl': settings.JENGA_CHECKOUT_REDIRECT_URL
            }
            
            response = requests.post(
                f"{self.base_url}/payments/v3/c2b/checkout",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"C2B checkout initiated: {reference}")
                return {
                    'success': True,
                    'checkout_id': data.get('checkoutId'),
                    'checkout_url': data.get('checkoutUrl'),
                    'reference': reference
                }
            else:
                logger.error(f"C2B checkout failed: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("C2B checkout error")
            return {'success': False, 'error': str(e)}
    
    def get_c2b_transaction_status(self, checkout_id):
        """
        Check status of a C2B transaction.
        Use this for polling if webhook is delayed.
        """
        try:
            headers = self._get_headers()
            
            response = requests.get(
                f"{self.base_url}/payments/v3/c2b/status/{checkout_id}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'status': data.get('status'),
                    'amount': data.get('amount'),
                    'reference': data.get('reference'),
                    'mpesa_receipt': data.get('mpesaReceiptNumber')
                }
            else:
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("C2B status check error")
            return {'success': False, 'error': str(e)}
    
    # ============================================================
    # B2C (Business to Customer) - Payouts to Individuals
    # ============================================================
    
    def initiate_b2c_payout(self, amount, recipient_phone, recipient_name, reference, reason="Land Sale Payment"):
        """
        Initiate B2C payout to an individual's mobile wallet or bank account.
        Used for paying landowners and agents.
        
        Args:
            amount: Payout amount (Decimal)
            recipient_phone: Recipient's phone number
            recipient_name: Recipient's full name
            reference: Unique transaction reference
            reason: Payment reason
            
        Returns:
            dict: Payout response with status
        """
        try:
            headers = self._get_headers()
            
            payload = {
                'merchantCode': self.merchant_code,
                'amount': str(float(amount)),
                'currencyCode': 'KES',
                'reference': reference,
                'reason': reason,
                'customer': {
                    'phoneNumber': recipient_phone,
                    'name': recipient_name
                },
                'callbackUrl': settings.JENGA_WEBHOOK_B2C_URL
            }
            
            response = requests.post(
                f"{self.base_url}/payments/v3/b2c/payout",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"B2C payout initiated: {reference}")
                return {
                    'success': True,
                    'transaction_id': data.get('transactionId'),
                    'reference': reference,
                    'status': 'PROCESSING'
                }
            else:
                logger.error(f"B2C payout failed: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("B2C payout error")
            return {'success': False, 'error': str(e)}
    
    def get_b2c_transaction_status(self, transaction_id):
        """
        Check status of a B2C transaction.
        """
        try:
            headers = self._get_headers()
            
            response = requests.get(
                f"{self.base_url}/payments/v3/b2c/status/{transaction_id}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'status': data.get('status'),
                    'amount': data.get('amount'),
                    'reference': data.get('reference')
                }
            else:
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("B2C status check error")
            return {'success': False, 'error': str(e)}
    
    # ============================================================
    # B2B (Business to Business) - Corporate Settlements
    # ============================================================
    
    def initiate_b2b_transfer(self, amount, recipient_account_number, recipient_bank_code,
                              recipient_account_name, recipient_branch_code, reference, 
                              reason="Professional Services"):
        """
        Initiate B2B transfer to a business entity's corporate account.
        Used for paying law firms, surveyors, input suppliers, etc.
        
        Args:
            amount: Transfer amount (Decimal)
            recipient_account_number: Business account number
            recipient_bank_code: Bank code (e.g., '68' for Equity)
            recipient_account_name: Business account name
            recipient_branch_code: Branch code
            reference: Unique transaction reference
            reason: Payment reason
            
        Returns:
            dict: Transfer response with status
        """
        try:
            headers = self._get_headers()
            
            payload = {
                'merchantCode': self.merchant_code,
                'sourceAccount': {
                    'accountNumber': self.corporate_account['account_number'],
                    'bankCode': self.corporate_account['bank_code']
                },
                'destinationAccount': {
                    'accountNumber': recipient_account_number,
                    'bankCode': recipient_bank_code,
                    'accountName': recipient_account_name,
                    'branchCode': recipient_branch_code
                },
                'amount': str(float(amount)),
                'currencyCode': 'KES',
                'reference': reference,
                'reason': reason,
                'callbackUrl': settings.JENGA_WEBHOOK_B2B_URL
            }
            
            response = requests.post(
                f"{self.base_url}/payments/v3/b2b/transfer",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"B2B transfer initiated: {reference}")
                return {
                    'success': True,
                    'transaction_id': data.get('transactionId'),
                    'reference': reference,
                    'status': 'PROCESSING'
                }
            else:
                logger.error(f"B2B transfer failed: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("B2B transfer error")
            return {'success': False, 'error': str(e)}
    
    def get_b2b_transaction_status(self, transaction_id):
        """
        Check status of a B2B transaction.
        """
        try:
            headers = self._get_headers()
            
            response = requests.get(
                f"{self.base_url}/payments/v3/b2b/status/{transaction_id}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'status': data.get('status'),
                    'amount': data.get('amount'),
                    'reference': data.get('reference')
                }
            else:
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("B2B status check error")
            return {'success': False, 'error': str(e)}
    
    # ============================================================
    # Helper Methods
    # ============================================================
    
    def get_balance(self, account_number=None):
        """
        Get balance of corporate account or specific account.
        """
        try:
            headers = self._get_headers()
            account = account_number or self.corporate_account['account_number']
            
            response = requests.get(
                f"{self.base_url}/accounts/v3/balance/{account}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'account_number': account,
                    'balance': Decimal(data.get('availableBalance', 0)),
                    'currency': data.get('currency', 'KES')
                }
            else:
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("Balance check error")
            return {'success': False, 'error': str(e)}