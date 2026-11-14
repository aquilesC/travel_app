"""API foundation (v4 #21) and app login (v4 #22)."""

import json

from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from api.openapi import CONTRACT, schema_json

LOGIN = "/_allauth/app/v1/auth/login"


class ApiTestCase(TestCase):
    def setUp(self):
        cache.clear()  # allauth's login rate limit counts per IP across tests
        self.user = get_user_model().objects.create_user(
            "aquiles", email="aquiles@example.com", password="secret-pw-123", first_name="Aquiles")

    def app_login(self, email="aquiles@example.com", password="secret-pw-123"):
        response = self.client.post(LOGIN, {"email": email, "password": password},
                                    content_type="application/json",
                                    HTTP_USER_AGENT="Trips/1.0 (iPhone; iOS 26.1)")
        return response

    def token(self):
        response = self.app_login()
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["meta"]["session_token"]

    def api(self, method, path, token=None, data=None, client=None, **extra):
        client = client or Client()
        if token:
            extra["HTTP_X_SESSION_TOKEN"] = token
        kwargs = {"content_type": "application/json", **extra}
        if data is not None:
            kwargs["data"] = json.dumps(data)
        return getattr(client, method)(f"/api/v1{path}", **kwargs)

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(response.json()["error"]["code"], code)


class FoundationTests(ApiTestCase):
    def test_health_needs_no_login(self):
        response = self.api("get", "/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["api_version"], "1")
        self.assertIn("server_time", response.json())

    def test_no_auth_is_401_json_not_a_redirect(self):
        self.assertError(self.api("get", "/me"), 401, "unauthenticated")

    def test_unknown_url_is_404(self):
        self.assertEqual(self.api("get", "/nope").status_code, 404)

    def test_session_post_without_csrf_is_rejected(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(self.api("get", "/me", client=browser).status_code, 200)
        response = self.api("patch", "/me", data={"first_name": "X"}, client=browser)
        self.assertIn(response.status_code, (401, 403))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Aquiles")

    def test_session_post_with_csrf_works(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        browser.get("/account/")  # sets the CSRF cookie
        token = browser.cookies["csrftoken"].value
        response = self.api("patch", "/me", data={"first_name": "Aq"}, client=browser,
                            HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["first_name"], "Aq")

    def test_validation_error_shape(self):
        response = self.api("patch", "/me", token=self.token(), data={"first_name": 12})
        self.assertError(response, 422, "invalid")
        self.assertIn("first_name", response.json()["error"]["fields"])

    def test_operation_ids_are_unique(self):
        import json

        ids = [op["operationId"] for path in json.loads(schema_json())["paths"].values() for op in path.values()]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_contract_is_up_to_date(self):
        self.assertEqual(
            CONTRACT.read_text(), schema_json(),
            "The API changed: run `manage.py export_openapi --output api/openapi.json` and commit it.")


class AppAuthTests(ApiTestCase):
    def test_login_returns_token_that_works(self):
        token = self.token()
        response = self.api("get", "/me", token=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Aquiles")

    def test_wrong_password(self):
        self.assertEqual(self.app_login(password="wrong").status_code, 400)
        self.assertError(self.api("get", "/me", token="made-up"), 401, "unauthenticated")

    def test_repeated_wrong_passwords_lock_the_account_for_a_while(self):
        for _ in range(5):
            self.assertEqual(self.app_login(password="wrong").status_code, 400)
        locked = self.app_login()  # even the right password is refused now
        self.assertEqual(locked.status_code, 400)
        self.assertIn("too many", locked.content.decode().lower())

    def test_signup_is_closed(self):
        response = self.client.post("/_allauth/app/v1/auth/signup",
                                    {"email": "new@example.com", "password": "secret-pw-123"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(email="new@example.com").exists())

    def test_token_post_needs_no_csrf(self):
        response = self.api("patch", "/me", token=self.token(), data={"last_name": "C"},
                            client=Client(enforce_csrf_checks=True))
        self.assertEqual(response.status_code, 200, response.content)

    def test_signing_out_a_device_revokes_its_token(self):
        token = self.token()
        session = UserSession.objects.get(user=self.user)
        self.assertIn("Trips/1.0", session.user_agent)
        session.end()
        self.assertError(self.api("get", "/me", token=token), 401, "unauthenticated")

    def test_logout(self):
        token = self.token()
        response = self.client.delete("/_allauth/app/v1/auth/session", HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(response.status_code, 401)  # allauth: "logged out" is reported as 401
        self.assertError(self.api("get", "/me", token=token), 401, "unauthenticated")
