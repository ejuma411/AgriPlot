# listings/tests/test_sms.py
from django.test import TestCase
from django.conf import settings
from unittest.mock import patch, MagicMock
from listings.services.sms_service import TextSMSService

class SMSServiceTestCase(TestCase):
    """Test cases for SMS service"""
    
    def setUp(self):
        self.sms = TextSMSService()
        self.test_phone = "+254718810503"
    
    @patch('requests.Session.post')
    def test_send_sms_success(self, mock_post):
        """Test successful SMS sending"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'responses': [{'respose-code': 200, 'response-description': 'Success'}]
        }
        mock_post.return_value = mock_response
        
        result = self.sms.send_sms(self.test_phone, "Test message")
        
        self.assertTrue(result['success'])
        self.assertTrue(result['data']['responses'][0]['respose-code'] in (200, '200'))
    
    @patch('requests.Session.post')
    def test_send_otp(self, mock_post):
        """Test OTP sending"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'responses': [{'respose-code': 200}]}
        mock_post.return_value = mock_response
        
        result = self.sms.send_otp(self.test_phone, "123456")
        
        self.assertTrue(result['success'])
        mock_post.assert_called_once()
