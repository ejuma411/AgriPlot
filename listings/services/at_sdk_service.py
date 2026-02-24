# listings/services/at_sdk_service.py
import africastalking
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class AfricaTalkingSDKService:
    """Service using official Africa's Talking SDK"""
    
    def __init__(self):
        # Initialize SDK
        self.username = 'sandbox' if settings.AT_SANDBOX else settings.AT_USERNAME
        self.api_key = settings.AT_API_KEY
        
        africastalking.initialize(self.username, self.api_key)
        self.sms = africastalking.SMS
        
        logger.info(f"📱 Initialized Africa's Talking SDK")
        logger.info(f"   Username: {self.username}")
        logger.info(f"   Environment: {'SANDBOX' if settings.AT_SANDBOX else 'PRODUCTION'}")
    
    def send_sms(self, phone_numbers, message):
        """Send SMS using official SDK"""
        
        if isinstance(phone_numbers, str):
            phone_numbers = [phone_numbers]
        
        try:
            # Format phone numbers
            formatted_numbers = []
            for number in phone_numbers:
                number = number.strip().replace(' ', '')
                if not number.startswith('+'):
                    number = '+' + number
                formatted_numbers.append(number)
            
            logger.info(f"📤 Sending SMS to {formatted_numbers}")
            
            # SDK handles sandbox automatically
            response = self.sms.send(message, formatted_numbers)
            
            logger.info(f"✅ SMS sent successfully: {response}")
            
            return {
                'success': True,
                'data': response,
                'message': f"SMS sent to {len(formatted_numbers)} recipient(s)"
            }
            
        except Exception as e:
            logger.error(f"❌ SMS sending failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_otp(self, phone_number, otp_code):
        """Send OTP verification code"""
        message = f"Your AgriPlot verification code is: {otp_code}. Valid for 10 minutes."
        return self.send_sms(phone_number, message)
    
    def send_task_assigned(self, phone_number, officer_name, plot_title):
        """Notify extension officer of new task"""
        message = f"Hi {officer_name}, you have been assigned to verify plot: {plot_title}. Login to AgriPlot to start."
        return self.send_sms(phone_number, message)