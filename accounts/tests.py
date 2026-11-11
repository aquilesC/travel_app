from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Profile


class ProfileTests(TestCase):
    def test_profile_created_with_user(self):
        """protects=every user gets a Profile automatically;
        fails_when=creating a user leaves no Profile row (WhatsApp lookup would crash);
        no_claim=admin inline rendering."""
        user = get_user_model().objects.create_user("ana", password="x")
        self.assertTrue(Profile.objects.filter(user=user).exists())

    def test_whatsapp_number_normalised(self):
        """protects=numbers are stored as bare E.164 so Twilio 'whatsapp:+..' senders match;
        fails_when=prefix or spaces are kept;
        no_claim=real Twilio sender formats beyond 'whatsapp:+<digits>'."""
        user = get_user_model().objects.create_user("ana", password="x")
        profile = user.profile
        profile.whatsapp_number = "whatsapp:+31 6 1234 5678"
        profile.save()
        profile.refresh_from_db()
        self.assertEqual(profile.whatsapp_number, "+31612345678")

    def test_invalid_number_rejected(self):
        """protects=only E.164 numbers pass validation;
        fails_when=a local number without country code validates;
        no_claim=number actually exists."""
        user = get_user_model().objects.create_user("ana", password="x")
        user.profile.whatsapp_number = "0612345678"
        with self.assertRaises(ValidationError):
            user.profile.full_clean()


class LoginRequiredTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        """protects=AC2: private pages need a login;
        fails_when=an anonymous request to / returns content;
        no_claim=every individual view (covered per view in trips tests)."""
        response = self.client.get("/account/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts/login/?next=/account/")

    def test_public_endpoints_open(self):
        """protects=health check and login page stay reachable anonymously;
        fails_when=they redirect to login (cloudflared health/login loop);
        no_claim=share pages (tested in trips)."""
        self.assertEqual(self.client.get("/healthz/").status_code, 200)
        self.assertEqual(self.client.get("/accounts/login/").status_code, 200)
