from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import LandownerProfile, Profile
from listings.forms import BuyerRegistrationForm, LandownerStep2Form
from security.models import PhoneOTP


class PhoneVerificationTests(TestCase):
    @override_settings(OTP_PROVIDER="sms", USE_SMS_MOCK=False)
    @patch("security.views_otp.SMSService.send_otp")
    def test_registration_otp_uses_sms_provider(self, mock_send_otp):
        mock_send_otp.return_value = {"success": True}
        session = self.client.session
        session["reg_phone"] = "0718810503"
        session["reg_data"] = {
            "username": "smsbuyer",
            "email": "smsbuyer@example.com",
            "first_name": "Sms",
            "last_name": "Buyer",
            "password": "secret123",
            "role": "buyer",
            "phone": "0718810503",
        }
        session.save()

        response = self.client.get(reverse("security:send_otp"))

        self.assertRedirects(response, reverse("security:verify_otp"))
        self.assertTrue(
            PhoneOTP.objects.filter(phone="0718810503", purpose="registration").exists()
        )
        mock_send_otp.assert_called_once()

    @override_settings(REQUIRE_CONTACT_VERIFICATION=True, OTP_PROVIDER="sms")
    def test_sms_only_contact_verification_allows_listing_access(self):
        user = get_user_model().objects.create_user(
            username="verified_landowner",
            password="secret123",
            email="owner@example.com",
        )
        profile, _ = Profile.objects.get_or_create(
            user=user,
            defaults={"role": "landowner"},
        )
        profile.phone = "0718810503"
        profile.phone_verified = True
        profile.email_verified = False
        profile.save(update_fields=["phone", "phone_verified", "email_verified"])
        LandownerProfile.objects.create(
            user=user,
            national_id=SimpleUploadedFile("owner_id.txt", b"id"),
            kra_pin=SimpleUploadedFile("owner_pin.txt", b"pin"),
            verified=True,
        )
        self.client.login(username="verified_landowner", password="secret123")

        response = self.client.get(reverse("listings:add_plot"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add Plot")

    def test_buyer_registration_rejects_duplicate_email_and_phone(self):
        existing_user = get_user_model().objects.create_user(
            username="existingbuyer",
            password="secret123",
            email="taken@example.com",
        )
        existing_profile, _ = Profile.objects.get_or_create(
            user=existing_user,
            defaults={"role": "buyer"},
        )
        existing_profile.phone = "0718810503"
        existing_profile.save(update_fields=["phone"])

        form = BuyerRegistrationForm(
            data={
                "username": "newbuyer",
                "email": "taken@example.com",
                "first_name": "New",
                "last_name": "Buyer",
                "phone": "+254718810503",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertIn("phone", form.errors)

    def test_landowner_contact_step_rejects_duplicate_phone(self):
        existing_user = get_user_model().objects.create_user(
            username="existingowner",
            password="secret123",
            email="owner@example.com",
        )
        existing_profile, _ = Profile.objects.get_or_create(
            user=existing_user,
            defaults={"role": "landowner"},
        )
        existing_profile.phone = "0718810503"
        existing_profile.save(update_fields=["phone"])

        form = LandownerStep2Form(
            data={
                "phone": "0718810503",
                "region": "Rift Valley",
                "city": "Nakuru",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)
