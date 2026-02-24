# listings/services/sms_service.py

import requests
import logging
import time
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class AfricaTalkingService:
    """Service for sending SMS via Africa's Talking API with retry logic"""
    
    def __init__(self, retries=3):
        self.base_url = 'https://api.sandbox.africastalking.com/version1/messaging'
        self.username = 'sandbox'
        self.api_key = settings.AT_API_KEY
        self.retries = retries
        
        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        
        logger.info(f"📱 SMS Service initialized with {retries} retries")
    
    def send_sms(self, phone_numbers, message, attempt=1):
        """Send SMS with automatic retry on failure"""
        if isinstance(phone_numbers, str):
            phone_numbers = [phone_numbers]
        
        # Format phone numbers
        formatted_numbers = []
        for number in phone_numbers:
            number = number.strip().replace(' ', '')
            if not number.startswith('+'):
                number = '+' + number
            formatted_numbers.append(number)
        
        data = {
            'username': self.username,
            'to': ','.join(formatted_numbers),
            'message': message,
        }
        
        headers = {
            'Accept': 'application/json',
            'apiKey': self.api_key
        }
        
        try:
            logger.info(f"📤 Attempt {attempt}: Sending SMS to {formatted_numbers}")
            
            response = self.session.post(
                self.base_url,
                headers=headers,
                data=data,
                timeout=10
            )
            
            if response.status_code == 201 or response.status_code == 200:
                result = response.json()
                logger.info(f"✅ SMS sent successfully")
                return {
                    'success': True,
                    'data': result,
                    'message': f"SMS sent to {len(formatted_numbers)} recipient(s)"
                }
            else:
                logger.error(f"❌ SMS failed: {response.status_code}")
                return {
                    'success': False,
                    'error': f"API returned {response.status_code}"
                }
                
        except Exception as e:
            logger.error(f"❌ Attempt {attempt} failed: {str(e)}")
            
            # Retry logic
            if attempt < self.retries:
                wait_time = attempt * 2
                logger.info(f"⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                return self.send_sms(phone_numbers, message, attempt + 1)
            else:
                return {
                    'success': False,
                    'error': f"Failed after {self.retries} attempts: {str(e)}"
                }
    
    # Keep all your existing notification methods
    def send_otp(self, phone_number, otp_code):
        if getattr(settings, "USE_SMS_MOCK", False):
            logger.info(f"[SMS MOCK] OTP for {phone_number}: {otp_code}")
            return {
                'success': True,
                'data': {'mock': True},
                'message': 'SMS mocked in dev'
            }
        message = f"Your AgriPlot verification code is: {otp_code}. Valid for 10 minutes."
        return self.send_sms(phone_number, message)
    
    def send_task_assigned(self, phone_number, officer_name, plot_title):
        message = f"🔔 NEW TASK: Hi {officer_name}, you have been assigned to verify plot '{plot_title}'."
        return self.send_sms(phone_number, message)
    
    def send_plot_approved(self, phone_number, plot_title):
        message = f"✅ GREAT NEWS! Your plot '{plot_title}' has been APPROVED and is now live!"
        return self.send_sms(phone_number, message)
    
    def send_plot_rejected(self, phone_number, plot_title, reason):
        message = f"📝 PLOT UPDATE: Your plot '{plot_title}' was not approved. Reason: {reason[:100]}"
        return self.send_sms(phone_number, message)
    
    def send_reminder(self, phone_number, task_type, plot_title):
        message = f"⏰ REMINDER: You have a pending {task_type} for plot '{plot_title}'."
        return self.send_sms(phone_number, message)
    
    def send_changes_requested(self, phone_number, plot_title, requested_by):
        message = f"📋 CHANGES REQUESTED: {requested_by} has requested changes to your plot '{plot_title}'."
        return self.send_sms(phone_number, message)
