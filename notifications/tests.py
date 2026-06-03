from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.forms import AccountDetailsForm
from accounts.models import Profile
from notifications.models import Notification
from notifications.notification_service import NotificationService


class RoleDecisionNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="role-user",
            email="role-user@example.com",
            password="safe-pass-123",
        )

    @patch("notifications.notification_service.NotificationService.send_email")
    def test_notify_role_decision_emits_approval_notification(self, mock_send_email):
        notification = NotificationService.notify_role_decision(
            user=self.user,
            role="Agent",
            approved=True,
            decided_by=self.user,
        )

        self.assertIsNotNone(notification)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notification.notification_type, "role_approved")
        self.assertEqual(notification.title, "Role Approved: Agent")
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args.kwargs["template"], "role_approved")

    @patch("notifications.notification_service.NotificationService.send_email")
    def test_notify_role_decision_emits_rejection_notification(self, mock_send_email):
        notification = NotificationService.notify_role_decision(
            user=self.user,
            role="Landowner",
            approved=False,
            decided_by=self.user,
            reason="Please upload the missing documents.",
        )

        self.assertIsNotNone(notification)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notification.notification_type, "role_rejected")
        self.assertEqual(notification.title, "Role Rejected: Landowner")
        self.assertIn("rejected", notification.message.lower())
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args.kwargs["template"], "role_rejected")


class IntentLabelTests(TestCase):
    def test_primary_intent_labels_are_professional(self):
        form = AccountDetailsForm()
        labels = dict(form.fields["intent"].choices)

        self.assertEqual(labels["buy"], "Buying Land")
        self.assertEqual(labels["lease_in"], "Leasing or Renting Land In")
        self.assertEqual(labels["sell"], "Selling Land")
        self.assertEqual(labels["lease_out"], "Leasing or Renting Land Out")
        self.assertEqual(labels["professional"], "Providing Land Services")
