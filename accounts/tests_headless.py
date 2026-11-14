"""allauth headless API used by the iPhone app (/_allauth/app/v1/...), and robots.txt."""

import json

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase

API = "/_allauth/app/v1"


class HeadlessAppTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("aquiles", email="aq@example.com", password="Old-Secret-1")
        EmailAddress.objects.create(user=user, email="aq@example.com", verified=True, primary=True)
        self.user = user

    def post(self, path, data, **headers):
        return self.client.post(API + path, json.dumps(data), content_type="application/json", **headers)

    def test_login_session_and_logout(self):
        """protects=the app can log in with email+password, use the session token, and log out;
        fails_when=the login endpoint 404s (the reported bug), the token isn't accepted, or logout keeps it alive;
        no_claim=the iPhone app's own handling of the response."""
        response = self.post("/auth/login", {"email": "aq@example.com", "password": "Old-Secret-1"})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        token = body["meta"]["session_token"]
        self.assertTrue(body["meta"]["is_authenticated"])
        self.assertEqual(body["data"]["user"]["email"], "aq@example.com")

        auth = {"HTTP_X_SESSION_TOKEN": token}
        self.assertEqual(self.client.get(API + "/auth/session", **auth).status_code, 200)
        self.assertEqual(self.client.delete(API + "/auth/session", **auth).status_code, 401)
        self.assertEqual(self.client.get(API + "/auth/session", **auth).status_code, 410)

    def test_wrong_password_and_closed_signup(self):
        """protects=bad credentials are refused; the app can't create accounts (invite only);
        fails_when=a wrong password logs in or signup via the API succeeds;
        no_claim=rate limiting thresholds (allauth defaults)."""
        response = self.post("/auth/login", {"email": "aq@example.com", "password": "nope"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("session_token", response.json().get("meta", {}))
        signup = self.post("/auth/signup", {"email": "new@example.com", "password": "Fresh-Pass-2026"})
        self.assertEqual(signup.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(email="new@example.com").exists())

    def test_browser_client_not_exposed(self):
        """protects=only the app client is enabled, not the browser (cookie) variant;
        fails_when=/_allauth/browser/... answers;
        no_claim=future needs for a separate web frontend."""
        self.assertEqual(self.client.get("/_allauth/browser/v1/auth/session").status_code, 404)


class RobotsTests(TestCase):
    def test_robots_disallow_all(self):
        """protects=crawlers are asked to stay out of the private journal;
        fails_when=robots.txt 404s or allows crawling;
        no_claim=crawlers that ignore robots.txt (pages need login anyway)."""
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("Disallow: /", response.content.decode())
