from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile


class AccountUpgradeFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="buyer1",
            email="buyer@example.com",
            password="safe-pass-123",
            first_name="Buyer",
            last_name="One",
        )
        Profile.objects.create(user=self.user, phone="0712345678", role="buyer")

    def test_profile_management_shows_upgrade_actions_for_buyer(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("listings:profile_management"))

        self.assertContains(response, "Upgrade This Account")
        self.assertContains(response, "Add Landowner Role")
        self.assertContains(response, "Add Agent Role")
        self.assertContains(response, "Request Extension Officer Role")
        self.assertContains(response, "Request Land Surveyor Role")
        self.assertContains(
            response,
            "Reuse this same username, profile details, and password",
        )

    def test_extension_officer_entrypoint_redirects_logged_in_buyer_to_request_form(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("listings:register_buyer") + "?role=extension_officer"
        )

        self.assertRedirects(response, reverse("verification:request_extension_officer"))

    def test_buyer_registration_page_explains_reuse_for_verification_roles(self):
        response = self.client.get(
            reverse("listings:register_buyer") + "?role=land_surveyor"
        )

        self.assertContains(response, "Create your buyer account first")
        self.assertContains(response, "same username, details, and password")
        self.assertContains(response, "Continue to Land Surveyor Request")

    def test_agent_pages_differentiate_registration_and_upgrade_flows(self):
        public_response = self.client.get(reverse("listings:register_agent"))
        self.assertContains(public_response, "Already registered as a buyer?")
        self.assertContains(public_response, "upgrade from your profile")

        self.client.force_login(self.user)
        upgrade_response = self.client.get(reverse("listings:register_agent"))
        self.assertContains(upgrade_response, "Upgrade to Agent")
        self.assertContains(upgrade_response, "username, contact details, and password")

    def test_upgrade_forms_prefill_username_and_email(self):
        self.client.force_login(self.user)

        landowner_response = self.client.get(reverse("listings:register_landowner_upgrade"))
        self.assertContains(landowner_response, 'value="buyer1"')
        self.assertContains(landowner_response, 'value="buyer@example.com"')
        self.assertContains(landowner_response, 'value="0712345678"')
        self.assertNotContains(landowner_response, 'name="phone"')

        agent_response = self.client.get(reverse("listings:register_agent"))
        self.assertContains(agent_response, 'value="buyer1"')
        self.assertContains(agent_response, 'value="buyer@example.com"')
        self.assertContains(agent_response, 'value="0712345678"')
        self.assertNotContains(agent_response, 'name="phone"')

    def test_role_request_forms_reuse_account_phone_without_duplicate_input(self):
        self.client.force_login(self.user)

        extension_response = self.client.get(
            reverse("verification:request_extension_officer")
        )
        self.assertContains(extension_response, 'value="buyer1"')
        self.assertContains(extension_response, 'value="buyer@example.com"')
        self.assertContains(extension_response, 'value="0712345678"')
        self.assertNotContains(extension_response, 'name="phone"')

        surveyor_response = self.client.get(
            reverse("verification:request_land_surveyor")
        )
        self.assertContains(surveyor_response, 'value="buyer1"')
        self.assertContains(surveyor_response, 'value="buyer@example.com"')
        self.assertContains(surveyor_response, 'value="0712345678"')
        self.assertNotContains(surveyor_response, 'name="phone"')
