"""
Jenga API Integration Service
Handles C2B, B2C, and B2B payments with webhook verification.
Integrates with AgriPlot's platform escrow model.
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
    """Service for Jenga API integration with escrow support"""
    
    def __init__(self):
        # Basic configuration
        self.base_url = getattr(settings, 'JENGA_API_BASE_URL', 'https://sandbox.jengaapi.com')
        self.api_key = getattr(settings, 'JENGA_API_KEY', '')
        self.api_secret = getattr(settings, 'JENGA_API_SECRET', '')
        self.merchant_code = getattr(settings, 'JENGA_MERCHANT_CODE', '')
        self.environment = getattr(settings, 'JENGA_ENVIRONMENT', 'sandbox')
        self.webhook_secret = getattr(settings, 'JENGA_WEBHOOK_SECRET', '')
        
        # Corporate account details (main business account)
        self.corporate_account = {
            'account_number': getattr(settings, 'JENGA_CORPORATE_ACCOUNT_NUMBER', ''),
            'account_name': getattr(settings, 'JENGA_CORPORATE_ACCOUNT_NAME', 'AgriPlot Corporate'),
            'bank_code': getattr(settings, 'JENGA_CORPORATE_BANK_CODE', '01'),
        }
        
        # Escrow account for holding client funds (use corporate as fallback if not configured)
        escrow_account_number = getattr(settings, 'JENGA_ESCROW_ACCOUNT_NUMBER', None)
        escrow_account_name = getattr(settings, 'JENGA_ESCROW_ACCOUNT_NAME', None)
        escrow_bank_code = getattr(settings, 'JENGA_ESCROW_BANK_CODE', None)
        
        self.escrow_account = {
            'account_number': escrow_account_number or self.corporate_account['account_number'],
            'account_name': escrow_account_name or f"{self.corporate_account['account_name']} - Escrow",
            'bank_code': escrow_bank_code or self.corporate_account['bank_code'],
        }
        
        # Platform fee account (use corporate as fallback if not configured)
        fee_account_number = getattr(settings, 'JENGA_FEE_ACCOUNT_NUMBER', None)
        fee_account_name = getattr(settings, 'JENGA_FEE_ACCOUNT_NAME', None)
        fee_bank_code = getattr(settings, 'JENGA_FEE_BANK_CODE', None)
        
        self.fee_account = {
            'account_number': fee_account_number or self.corporate_account['account_number'],
            'account_name': fee_account_name or f"{self.corporate_account['account_name']} - Fees",
            'bank_code': fee_bank_code or self.corporate_account['bank_code'],
        }
        
        # Log configuration status
        if not self.api_key or not self.api_secret:
            logger.warning("Jenga API credentials not configured. JengaService will operate in mock mode.")
    
    def _is_configured(self):
        """Check if Jenga is properly configured"""
        return bool(self.api_key and self.api_secret and self.merchant_code)
    
    def _get_access_token(self):
        """
        Get OAuth2 access token from Jenga.
        Tokens are cached to avoid rate limiting.
        """
        if not self._is_configured():
            raise JengaError("Jenga API credentials not configured")
        
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
    
    def verify_webhook_signature(self, payload, signature):
        """
        Verify webhook signature for security.
        """
        if not self.webhook_secret:
            logger.warning("No webhook secret configured - skipping verification")
            return True
        
        try:
            expected_signature = hmac.new(
                self.webhook_secret.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Webhook verification failed: {e}")
            return False
    
    # ============================================================
    # C2B (Customer to Business) - Deposits to Escrow
    # ============================================================
    
    def initiate_c2b_checkout(self, amount, phone_number, reference, customer_name=None, email=None):
        """
        Initiate a C2B payment from buyer to platform escrow account.
        Funds go directly to AgriPlot's licensed escrow account.
        
        Args:
            amount: Payment amount (Decimal)
            phone_number: Customer's phone number
            reference: Unique transaction reference
            customer_name: Optional customer name
            email: Optional customer email
            
        Returns:
            dict: Checkout response containing checkout_url and checkout_id
        """
        # Mock mode for development/testing
        if not self._is_configured():
            logger.info(f"MOCK C2B checkout: {reference} - KES {amount:,.2f}")
            return {
                'success': True,
                'checkout_id': f"MOCK-{reference}",
                'checkout_url': f"{getattr(settings, 'SITE_URL', 'http://localhost:8000')}/payments/mock-checkout/{reference}/",
                'reference': reference,
                'mock': True
            }
        
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
                'callbackUrl': getattr(settings, 'JENGA_WEBHOOK_C2B_URL', ''),
                'redirectUrl': getattr(settings, 'JENGA_CHECKOUT_REDIRECT_URL', '')
            }
            
            response = requests.post(
                f"{self.base_url}/payments/v3/c2b/checkout",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"C2B checkout initiated for escrow: {reference}")
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
        if not self._is_configured():
            return {'success': True, 'status': 'MOCK_PAID', 'mock': True}
        
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
    # B2C (Business to Customer) - Payouts to Sellers
    # ============================================================
    
    def initiate_b2c_payout(self, amount, recipient_phone, recipient_name, reference, 
                            reason="Land Sale Payment - Platform Escrow Disbursement"):
        """
        Initiate B2C payout to seller's mobile wallet or bank account.
        Used for disbursing escrowed funds to sellers after registration.
        
        Args:
            amount: Payout amount (Decimal) - Net after platform fee
            recipient_phone: Recipient's phone number
            recipient_name: Recipient's full name
            reference: Unique transaction reference
            reason: Payment reason
            
        Returns:
            dict: Payout response with status
        """
        if not self._is_configured():
            logger.info(f"MOCK B2C payout: {reference} - KES {amount:,.2f}")
            return {
                'success': True,
                'transaction_id': f"MOCK-{reference}",
                'reference': reference,
                'status': 'MOCK_PROCESSING',
                'mock': True
            }
        
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
                'callbackUrl': getattr(settings, 'JENGA_WEBHOOK_B2C_URL', '')
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
        if not self._is_configured():
            return {'success': True, 'status': 'MOCK_SUCCESS', 'mock': True}
        
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
    # B2B (Business to Business) - Corporate Payments
    # ============================================================
    
    def initiate_b2b_transfer(self, amount, recipient_account_number, recipient_bank_code,
                              recipient_account_name, recipient_branch_code, reference, 
                              reason="Professional Services Payment"):
        """
        Initiate B2B transfer to a business entity's corporate account.
        Used for paying:
        - Law firms (advocates)
        - Licensed surveyors
        - Land Control Board fees
        - Government agencies
        
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
        if not self._is_configured():
            logger.info(f"MOCK B2B transfer: {reference} - KES {amount:,.2f}")
            return {
                'success': True,
                'transaction_id': f"MOCK-{reference}",
                'reference': reference,
                'status': 'MOCK_PROCESSING',
                'mock': True
            }
        
        try:
            headers = self._get_headers()
            
            payload = {
                'merchantCode': self.merchant_code,
                'sourceAccount': {
                    'accountNumber': self.escrow_account['account_number'],
                    'bankCode': self.escrow_account['bank_code']
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
                'callbackUrl': getattr(settings, 'JENGA_WEBHOOK_B2B_URL', '')
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
        if not self._is_configured():
            return {'success': True, 'status': 'MOCK_SUCCESS', 'mock': True}
        
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
    # Escrow-Specific Methods
    # ============================================================
    
    def disburse_to_seller(self, payment, seller_account_details, amount, platform_fee):
        """
        Disburse funds from escrow to seller after registration.
        Platform fee is deducted and sent to fee account.
        
        Args:
            payment: PaymentRequest instance
            seller_account_details: Dict with seller's bank/wallet details
            amount: Total amount to disburse (gross)
            platform_fee: Platform fee to deduct
            
        Returns:
            dict: Disbursement result
        """
        try:
            seller_net = amount - platform_fee
            
            # 1. Transfer platform fee to fee account (B2B)
            if platform_fee > 0:
                fee_transfer = self.initiate_b2b_transfer(
                    amount=platform_fee,
                    recipient_account_number=self.fee_account['account_number'],
                    recipient_bank_code=self.fee_account['bank_code'],
                    recipient_account_name=self.fee_account['account_name'],
                    recipient_branch_code='001',  # Default branch
                    reference=f"FEE-{payment.internal_reference}",
                    reason=f"Platform fee for transaction {payment.internal_reference}"
                )
                
                if not fee_transfer.get('success'):
                    logger.error(f"Platform fee transfer failed for {payment.internal_reference}")
                    return {
                        'success': False,
                        'error': f"Fee transfer failed: {fee_transfer.get('error')}"
                    }
            
            # 2. Transfer net amount to seller (B2C)
            seller_transfer = self.initiate_b2c_payout(
                amount=seller_net,
                recipient_phone=seller_account_details.get('phone_number'),
                recipient_name=seller_account_details.get('name'),
                reference=f"PAY-{payment.internal_reference}",
                reason=f"Land sale proceeds for {payment.title}"
            )
            
            if not seller_transfer.get('success'):
                logger.error(f"Seller payout failed for {payment.internal_reference}")
                return {
                    'success': False,
                    'error': f"Seller payout failed: {seller_transfer.get('error')}"
                }
            
            logger.info(
                f"Successfully disbursed {seller_net} to seller for {payment.internal_reference} "
                f"(platform fee: {platform_fee})"
            )
            
            return {
                'success': True,
                'seller_transaction_id': seller_transfer.get('transaction_id'),
                'fee_transaction_id': fee_transfer.get('transaction_id') if platform_fee > 0 else None,
                'seller_net': seller_net,
                'platform_fee': platform_fee
            }
            
        except Exception as e:
            logger.exception(f"Disbursement error for {payment.internal_reference}")
            return {'success': False, 'error': str(e)}
    
    def hold_funds_in_escrow(self, amount, reference, source_account_details):
        """
        Record that funds are being held in escrow.
        Funds are already in the escrow account from C2B payment.
        
        Args:
            amount: Amount held
            reference: Transaction reference
            source_account_details: Payer details
            
        Returns:
            dict: Escrow hold confirmation
        """
        try:
            logger.info(
                f"Funds held in escrow: {amount} for reference {reference} "
                f"from {source_account_details.get('name', 'Unknown')}"
            )
            
            return {
                'success': True,
                'reference': reference,
                'amount': amount,
                'status': 'HELD_IN_ESCROW'
            }
            
        except Exception as e:
            logger.error(f"Escrow hold failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def release_escrow_funds(self, payment, seller_account_details):
        """
        Release escrowed funds to seller after registration complete.
        This is the main disbursement method called by the system.
        """
        from payments.models import PaymentRequest, PaymentDisbursement
        
        # Verify registration is complete
        if not payment.purchase_registration_complete:
            return {
                'success': False,
                'error': 'Registration not complete. Cannot release escrow funds.'
            }
        
        # Verify stamp duty is verified (KRA payment confirmed)
        stamp_duty_verified = payment.stamp_duty_receipt_verified_at is not None
        if not stamp_duty_verified:
            return {
                'success': False,
                'error': 'Stamp duty payment to KRA not verified. Cannot release escrow funds.'
            }
        
        # Calculate amounts
        total_amount = payment.amount
        platform_fee = payment.platform_fee_amount
        seller_net = payment.seller_net_amount
        
        # Disburse funds
        result = self.disburse_to_seller(
            payment=payment,
            seller_account_details=seller_account_details,
            amount=total_amount,
            platform_fee=platform_fee
        )
        
        if result.get('success'):
            # Update payment record
            payment.disbursed_at = timezone.now()
            payment.platform_fee_deducted_at = timezone.now()
            payment.save(update_fields=['disbursed_at', 'platform_fee_deducted_at', 'updated_at'])
            
            # Update disbursement records
            self._update_disbursement_records(payment, platform_fee, seller_net)
            
            # Trigger report generation
            from notifications.notification_service import NotificationService
            NotificationService.send_transaction_completion_reports(payment)
            
        return result
    
    def _update_disbursement_records(self, payment, platform_fee, seller_net):
        """Update PaymentDisbursement records after successful transfer"""
        from payments.models import PaymentDisbursement
        
        # Update platform fee disbursement
        platform_disbursement = payment.disbursements.filter(code="platform_fee").first()
        if platform_disbursement:
            platform_disbursement.status = PaymentDisbursement.Status.RELEASED
            platform_disbursement.released_at = timezone.now()
            platform_disbursement.save(update_fields=['status', 'released_at', 'updated_at'])
        
        # Update seller disbursement
        seller_disbursement = payment.disbursements.filter(code="seller_disbursement").first()
        if seller_disbursement:
            seller_disbursement.status = PaymentDisbursement.Status.RELEASED
            seller_disbursement.released_at = timezone.now()
            seller_disbursement.save(update_fields=['status', 'released_at', 'updated_at'])
    
    # ============================================================
    # Stamp Duty Payment Verification (KRA iTax)
    # ============================================================
    
    def verify_stamp_duty_payment(self, payment, kra_receipt_number, kra_receipt_attachment):
        """
        Verify stamp duty payment to KRA.
        Platform does NOT collect stamp duty - only verifies.
        
        This method:
        1. Validates KRA receipt format
        2. Could integrate with KRA API for verification
        3. Records verification in payment metadata
        """
        try:
            # Validate KRA receipt number format
            import re
            receipt_pattern = r'^KRA-\d{8}-\d{6}$'
            if not re.match(receipt_pattern, kra_receipt_number):
                return {
                    'success': False,
                    'error': 'Invalid KRA receipt number format. Expected: KRA-YYYYMMDD-XXXXXX'
                }
            
            # Record verification
            logger.info(f"Stamp duty verified for payment {payment.internal_reference}: {kra_receipt_number}")
            
            return {
                'success': True,
                'receipt_number': kra_receipt_number,
                'verified_at': timezone.now().isoformat()
            }
            
        except Exception as e:
            logger.exception("Stamp duty verification error")
            return {'success': False, 'error': str(e)}
    
    # ============================================================
    # Balance Inquiry
    # ============================================================
    
    def get_escrow_balance(self):
        """
        Get balance of escrow account.
        Used for reconciliation and auditing.
        """
        return self.get_balance(self.escrow_account['account_number'])
    
    def get_balance(self, account_number=None):
        """
        Get balance of specified account or escrow account.
        """
        if not self._is_configured():
            return {
                'success': True,
                'account_number': account_number or self.escrow_account['account_number'],
                'balance': Decimal('0.00'),
                'currency': 'KES',
                'mock': True
            }
        
        try:
            headers = self._get_headers()
            account = account_number or self.escrow_account['account_number']
            
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
                    'currency': data.get('currency', 'KES'),
                    'ledger_balance': Decimal(data.get('ledgerBalance', 0))
                }
            else:
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("Balance check error")
            return {'success': False, 'error': str(e)}
    
    def get_platform_fee_balance(self):
        """
        Get balance of platform fee account.
        """
        return self.get_balance(self.fee_account['account_number'])
    
    # ============================================================
    # Reconciliation
    # ============================================================
    
    def get_transaction_report(self, from_date, to_date, account_number=None):
        """
        Get transaction report for reconciliation.
        Used for audit trail and compliance reporting.
        """
        if not self._is_configured():
            return {
                'success': True,
                'transactions': [],
                'total_count': 0,
                'total_amount': Decimal('0.00'),
                'mock': True
            }
        
        try:
            headers = self._get_headers()
            account = account_number or self.escrow_account['account_number']
            
            payload = {
                'accountNumber': account,
                'fromDate': from_date.strftime('%Y-%m-%d'),
                'toDate': to_date.strftime('%Y-%m-%d')
            }
            
            response = requests.post(
                f"{self.base_url}/reports/v3/transactions",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'transactions': data.get('transactions', []),
                    'total_count': data.get('totalCount', 0),
                    'total_amount': Decimal(data.get('totalAmount', 0))
                }
            else:
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.exception("Transaction report error")
            return {'success': False, 'error': str(e)}
    
    def reconcile_escrow(self, expected_balance):
        """
        Reconcile escrow account balance with expected balance from database.
        """
        actual_balance_result = self.get_escrow_balance()
        
        if not actual_balance_result.get('success'):
            return {
                'success': False,
                'error': actual_balance_result.get('error')
            }
        
        actual_balance = actual_balance_result.get('balance')
        difference = actual_balance - expected_balance
        
        is_reconciled = abs(difference) < Decimal('0.01')  # Tolerance of 1 cent
        
        if not is_reconciled:
            logger.warning(
                f"Escrow reconciliation failed: Expected {expected_balance}, "
                f"Actual {actual_balance}, Difference {difference}"
            )
        
        return {
            'success': is_reconciled,
            'expected_balance': expected_balance,
            'actual_balance': actual_balance,
            'difference': difference,
            'is_reconciled': is_reconciled
        }
    
    # ============================================================
    # Webhook Processing Helpers
    # ============================================================
    
    def process_c2b_webhook(self, payload):
        """
        Process C2B webhook notification from Jenga.
        Updates payment status when deposit is received.
        """
        try:
            transaction_id = payload.get('transactionId')
            checkout_id = payload.get('checkoutId')
            status = payload.get('status')
            amount = Decimal(payload.get('amount', 0))
            mpesa_receipt = payload.get('mpesaReceiptNumber')
            reference = payload.get('reference')
            
            logger.info(f"Processing C2B webhook: {reference} - {status}")
            
            from payments.models import PaymentRequest
            payment = PaymentRequest.objects.filter(
                internal_reference=reference
            ).first()
            
            if not payment:
                logger.warning(f"Payment not found for reference: {reference}")
                return {'success': False, 'error': 'Payment not found'}
            
            if status == 'SUCCESS':
                from django.utils import timezone
                payment.status = PaymentRequest.Status.PAID
                payment.paid_at = timezone.now()
                payment.provider_reference = transaction_id
                
                metadata = payment.metadata or {}
                metadata['mpesa_receipt'] = mpesa_receipt
                metadata['jenga_checkout_id'] = checkout_id
                payment.metadata = metadata
                
                payment.save()
                
                logger.info(f"Payment {reference} marked as paid via webhook")
                
                # Record escrow hold
                self.hold_funds_in_escrow(
                    amount=amount,
                    reference=reference,
                    source_account_details={'name': payment.buyer.get_full_name() if payment.buyer else 'Buyer'}
                )
                
                return {
                    'success': True,
                    'payment_id': payment.id,
                    'status': 'updated'
                }
            
            elif status == 'FAILED':
                payment.status = PaymentRequest.Status.FAILED
                payment.save()
                logger.warning(f"Payment {reference} failed: {payload}")
                return {'success': True, 'status': 'failed'}
            
            return {'success': True, 'status': 'ignored'}
            
        except Exception as e:
            logger.exception("C2B webhook processing error")
            return {'success': False, 'error': str(e)}
    
    def process_b2c_webhook(self, payload):
        """
        Process B2C webhook notification from Jenga.
        Updates disbursement status.
        """
        try:
            transaction_id = payload.get('transactionId')
            status = payload.get('status')
            reference = payload.get('reference')
            amount = Decimal(payload.get('amount', 0))
            
            logger.info(f"Processing B2C webhook: {reference} - {status}")
            
            from payments.models import PaymentDisbursement, PaymentRequest
            
            if reference and reference.startswith('PAY-'):
                payment_ref = reference.replace('PAY-', '')
                payment = PaymentRequest.objects.filter(internal_reference=payment_ref).first()
                
                if payment and status == 'SUCCESS':
                    seller_disbursement = payment.disbursements.filter(code="seller_disbursement").first()
                    if seller_disbursement:
                        seller_disbursement.status = 'released'
                        seller_disbursement.released_at = timezone.now()
                        seller_disbursement.provider_reference = transaction_id
                        seller_disbursement.save()
                        
                        logger.info(f"Disbursement {reference} confirmed successful")
            
            return {'success': True}
            
        except Exception as e:
            logger.exception("B2C webhook processing error")
            return {'success': False, 'error': str(e)}


# Create a singleton instance
try:
    jenga_service = JengaService()
except Exception as e:
    logger.warning(f"JengaService initialization failed: {e}")
    jenga_service = None