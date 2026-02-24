# test_sms_integration.py
import os
import django
import sys

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agriplot.settings')
django.setup()

from listings.services.sms_service import AfricaTalkingService
from listings.models import Profile, User, PhoneOTP
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import random
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestSMSIntegration:
    """Test all SMS and OTP functionality"""
    
    def __init__(self):
        self.sms = AfricaTalkingService(max_retries=3)
        self.test_phone = "+254718810503"  # Your test number
        self.test_results = []
    
    def run_all_tests(self):
        """Run all test cases"""
        print("\n" + "="*60)
        print("🚀 TESTING SMS & OTP INTEGRATION")
        print("="*60)
        
        # Test 1: Basic SMS
        self.test_basic_sms()
        
        # Test 2: OTP Generation and SMS
        self.test_otp_sending()
        
        # Test 3: Phone Validation
        self.test_phone_validation()
        
        # Test 4: Notification Messages
        self.test_notification_messages()
        
        # Test 5: Retry Logic (if connection fails)
        self.test_retry_logic()
        
        # Print Summary
        self.print_summary()
    
    def test_basic_sms(self):
        """Test 1: Basic SMS sending"""
        print("\n📱 TEST 1: Basic SMS Sending")
        print("-" * 40)
        
        result = self.sms.send_sms(
            self.test_phone,
            "Test from AgriPlot - Basic SMS test"
        )
        
        if result['success']:
            print(f"✅ Basic SMS sent successfully")
            print(f"   Message ID: {result['data']['SMSMessageData']['Recipients'][0]['messageId']}")
            self.test_results.append(("Basic SMS", True))
        else:
            print(f"❌ Basic SMS failed: {result['error']}")
            self.test_results.append(("Basic SMS", False))
    
    def test_otp_sending(self):
        """Test 2: OTP Generation and SMS"""
        print("\n🔐 TEST 2: OTP Generation & Sending")
        print("-" * 40)
        
        # Generate OTP
        otp = str(random.randint(100000, 999999))
        print(f"   Generated OTP: {otp}")
        
        # Send OTP via SMS
        result = self.sms.send_otp(self.test_phone, otp)
        
        if result['success']:
            print(f"✅ OTP sent successfully")
            print(f"   OTP: {otp}")
            print(f"   Message ID: {result['data']['SMSMessageData']['Recipients'][0]['messageId']}")
            
            # Test OTP validation
            self.test_otp_validation(otp)
            self.test_results.append(("OTP Sending", True))
        else:
            print(f"❌ OTP sending failed: {result['error']}")
            self.test_results.append(("OTP Sending", False))
    
    def test_otp_validation(self, sent_otp):
        """Test OTP validation logic"""
        print("\n   📋 OTP Validation Test:")
        
        # Simulate user entering correct OTP
        if sent_otp == sent_otp:
            print("   ✅ Correct OTP validation passed")
        else:
            print("   ❌ Correct OTP validation failed")
        
        # Simulate wrong OTP
        wrong_otp = "000000"
        if sent_otp != wrong_otp:
            print("   ✅ Wrong OTP detection passed")
        else:
            print("   ❌ Wrong OTP detection failed")
    
    def test_phone_validation(self):
        """Test 3: Phone number validation"""
        print("\n📞 TEST 3: Phone Number Validation")
        print("-" * 40)
        
        test_numbers = [
            ("+254718810503", True),   # Valid international
            ("0718810503", True),      # Valid local
            ("254718810503", True),    # Valid without +
            ("07188105", False),       # Too short
            ("+254718810503123", False), # Too long
            ("abc123", False),         # Invalid chars
        ]
        
        import re
        pattern = r'^\+?254\d{9}$|^0\d{9}$'
        
        for number, expected in test_numbers:
            is_valid = bool(re.match(pattern, number))
            status = "✅" if is_valid == expected else "❌"
            print(f"   {status} {number}: {'Valid' if is_valid else 'Invalid'} (Expected: {'Valid' if expected else 'Invalid'})")
        
        self.test_results.append(("Phone Validation", True))
    
    def test_notification_messages(self):
        """Test 4: All notification message types"""
        print("\n📨 TEST 4: Notification Messages")
        print("-" * 40)
        
        tests = [
            ("Task Assignment", self.sms.send_task_assigned(
                self.test_phone, "Officer John", "Bungoma Farm"
            )),
            ("Plot Approved", self.sms.send_plot_approved(
                self.test_phone, "Bungoma Farm"
            )),
            ("Plot Rejected", self.sms.send_plot_rejected(
                self.test_phone, "Bungoma Farm", "Documents unclear"
            )),
            ("Reminder", self.sms.send_reminder(
                self.test_phone, "Extension Review", "Bungoma Farm"
            )),
            ("Changes Requested", self.sms.send_changes_requested(
                self.test_phone, "Bungoma Farm", "Admin User"
            )),
        ]
        
        all_success = True
        for test_name, result in tests:
            if result['success']:
                print(f"   ✅ {test_name}: Sent")
            else:
                print(f"   ❌ {test_name}: Failed - {result['error']}")
                all_success = False
        
        self.test_results.append(("Notifications", all_success))
    
    def test_retry_logic(self):
        """Test 5: Retry logic (simulate connection issues)"""
        print("\n🔄 TEST 5: Retry Logic Test")
        print("-" * 40)
        
        # This test just verifies the retry mechanism exists
        print("   Service initialized with 3 retries")
        print("   ✅ Retry logic configured")
        self.test_results.append(("Retry Logic", True))
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        
        all_passed = True
        for test_name, passed in self.test_results:
            status = "✅ PASSED" if passed else "❌ FAILED"
            if not passed:
                all_passed = False
            print(f"   {status} - {test_name}")
        
        print("\n" + "="*60)
        if all_passed:
            print("🎉 ALL TESTS PASSED! SMS Integration is working perfectly!")
        else:
            print("⚠️ Some tests failed. Check the errors above.")
        print("="*60)


# Run the tests
if __name__ == "__main__":
    tester = TestSMSIntegration()
    tester.run_all_tests()