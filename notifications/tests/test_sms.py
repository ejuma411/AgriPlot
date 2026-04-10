# listings/tests/test_sms.py
from django.test import TestCase, override_settings
from django.conf import settings
from unittest.mock import patch, MagicMock
from notifications.services.sms_service import TextSMSService

@override_settings(USE_SMS_MOCK=False)
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

    @override_settings(
        USE_SMS_MOCK=False,
        SMS_PROVIDER='opensms',
        OPENSMS_API_URL='https://www.opensms.co.ke/api/v3/',
        OPENSMS_API_TOKEN='test-token',
        OPENSMS_SENDER_ID='AgriPlot',
    )
    @patch('requests.Session.post')
    def test_send_sms_success_opensms(self, mock_post):
        """Test successful SMS sending via OpenSMS."""
        sms = TextSMSService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'message_id': 'abc123', 'status': 'success'}
        mock_post.return_value = mock_response

        result = sms.send_sms(self.test_phone, "Test message")

        self.assertTrue(result['success'])
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(kwargs['json']['phone'], '254718810503')
        self.assertEqual(kwargs['json']['message'], 'Test message')
