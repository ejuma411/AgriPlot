# listings/tests/test_sms_integration.py
from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock
from notifications.services.sms_service import TextSMSService

@override_settings(USE_SMS_MOCK=False)
class SMSIntegrationTestCase(TestCase):
    """Integration tests for SMS service"""
    
    def setUp(self):
        self.sms = TextSMSService()
        self.test_phone = "+254718810503"
    
    def test_phone_validation(self):
        """Test phone number validation"""
        from listings.forms import BaseUserRegistrationForm
        form = BaseUserRegistrationForm()
        
        # Valid numbers
        self.assertTrue(form.validate_phone("+254718810503"))
        self.assertTrue(form.validate_phone("0718810503"))
        
        # Invalid numbers
        with self.assertRaises(Exception):
            form.validate_phone("123")
    
    @patch('requests.Session.post')
    def test_all_notification_types(self, mock_post):
        """Test all SMS notification types"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'responses': [{'respose-code': 200}]}
        mock_post.return_value = mock_response
        
        # Test OTP
        result = self.sms.send_otp(self.test_phone, "123456")
        self.assertTrue(result['success'])
        
        # Test task assignment
        result = self.sms.send_task_assigned(self.test_phone, "John", "Test Plot")
        self.assertTrue(result['success'])
        
        # Test plot approved
        result = self.sms.send_plot_approved(self.test_phone, "Test Plot")
        self.assertTrue(result['success'])
        
        # Test reminder
        result = self.sms.send_reminder(self.test_phone, "Review", "Test Plot")
        self.assertTrue(result['success'])
