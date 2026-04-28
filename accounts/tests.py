from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
import socket
from unittest.mock import patch

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
        self.profile, _ = Profile.objects.get_or_create(user=self.user)
        self.profile.phone = "0712345678"
        self.profile.role = "buyer"
        self.profile.save()

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

    @patch("accounts.validators.socket.getaddrinfo")
    def test_email_validation_endpoint_rejects_duplicate_email(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [object()]

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("listings:validate_email_input"),
            {"email": "buyer@example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["exists"])

        other_user = User.objects.create_user(
            username="buyer2",
            email="taken@example.com",
            password="safe-pass-123",
        )
        other_profile, _ = Profile.objects.get_or_create(user=other_user)
        other_profile.phone = "0711111111"
        other_profile.role = "buyer"
        other_profile.save()
        duplicate_response = self.client.get(
            reverse("listings:validate_email_input"),
            {"email": "taken@example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        duplicate_payload = duplicate_response.json()
        self.assertFalse(duplicate_payload["valid"])
        self.assertTrue(duplicate_payload["exists"])

    @patch("accounts.validators.socket.getaddrinfo")
    def test_profile_edit_rejects_invalid_email_and_phone(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("domain lookup failed")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("listings:profile_edit"),
            data={
                "section": "account",
                "first_name": "Buyer",
                "last_name": "One",
                "email": "not-real@invalid-domain.zzz",
                "phone": "12345",
                "address": "Farm road",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Correct the account details below and try again.")
        self.assertContains(response, "This email domain does not appear to accept mail.")
        self.assertContains(response, "Enter a valid Kenyan phone number")


class DashboardAccessControlTests(TestCase):
    def test_dashboard_router_sends_buyer_to_saved_workspace(self):
        user = User.objects.create_user(
            username="buyer_workspace",
            password="safe-pass-123",
        )
        Profile.objects.get_or_create(user=user, defaults={"role": "buyer"})

        self.client.force_login(user)
        response = self.client.get(reverse("listings:dashboard_router"))

        self.assertRedirects(response, reverse("listings:saved_plots"))

    def test_dashboard_router_renders_finance_workspace_section(self):
        user = User.objects.create_user(
            username="finance_workspace",
            password="safe-pass-123",
        )
        Profile.objects.get_or_create(user=user, defaults={"role": "buyer"})
        finance_group, _ = Group.objects.get_or_create(name="Finance Admin")
        user.groups.add(finance_group)

        self.client.force_login(user)
        response = self.client.get(reverse("listings:dashboard_router"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escrow &amp; Payout Control")

    def test_staff_dashboard_legacy_url_redirects_to_single_entry_point(self):
        user = User.objects.create_user(
            username="ops_workspace",
            password="safe-pass-123",
            first_name="Olive",
        )
        Profile.objects.get_or_create(user=user, defaults={"role": "buyer"})
        user.is_staff = True
        user.save(update_fields=["is_staff"])

        self.client.force_login(user)
        response = self.client.get(reverse("listings:staff_dashboard"))

        self.assertRedirects(response, reverse("listings:dashboard_router"))

    def test_dashboard_router_shows_permission_filtered_modules(self):
        user = User.objects.create_user(
            username="ops_workspace_2",
            password="safe-pass-123",
            first_name="Olive",
        )
        Profile.objects.get_or_create(user=user, defaults={"role": "buyer"})
        user.is_staff = True
        user.save(update_fields=["is_staff"])

        self.client.force_login(user)
        response = self.client.get(reverse("listings:dashboard_router"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operations Workspace")
        self.assertContains(response, "Verification Queue")
        self.assertContains(response, "Task Assignment")
        self.assertContains(response, "Audit Trail")
        self.assertNotContains(response, "Escrow &amp; Payouts")
