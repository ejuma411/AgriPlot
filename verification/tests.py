from django.test import TestCase
from django.urls import reverse


class VerificationNamespaceTests(TestCase):
    def test_verification_dashboard_reverse(self):
        url = reverse("verification:verification_dashboard")
        self.assertTrue(url.startswith("/verify/verification/"))
