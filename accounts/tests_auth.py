"""Issues 14 (allauth) and 16 (invites)."""

import re
from datetime import date, timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from accounts.models import Invite
from trips.models import Trip

User = get_user_model()


def make_user(username, email, password="Old-Secret-1"):
    user = User.objects.create_user(username, email=email, password=password)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


class AllauthTests(TestCase):
    def setUp(self):
        self.user = make_user("aquiles", "aq@example.com")

    def test_login_with_email_not_username(self):
        """protects=AC14.1: email + password logs in; the username does not;
        fails_when=login by username still works or email login fails;
        no_claim=rate limiting of failed logins (allauth default, untested)."""
        response = self.client.post("/accounts/login/", {"login": "aquiles", "password": "Old-Secret-1"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post("/accounts/login/", {"login": "AQ@example.com", "password": "Old-Secret-1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_password_reset_cycle(self):
        """protects=AC14.2: reset email → link → new password works, old one doesn't;
        fails_when=no email, the link doesn't lead to a set-password form, or the old password survives;
        no_claim=Mailgun delivery (locmem backend)."""
        self.client.post("/accounts/password/reset/", {"email": "aq@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^\s]+/accounts/password/reset/key/[^\s]+/", mail.outbox[0].body).group(0)
        path = re.sub(r"^https?://[^/]+", "", link)
        response = self.client.get(path, follow=True)
        set_password_path = response.redirect_chain[-1][0] if response.redirect_chain else path
        response = self.client.post(set_password_path, {"password1": "Brand-New-Pass-9", "password2": "Brand-New-Pass-9"})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Brand-New-Pass-9"))
        self.assertFalse(self.user.check_password("Old-Secret-1"))

    def test_signup_closed_and_login_redirect(self):
        """protects=AC14.3-4: no public signup; protected pages send you to the allauth login;
        fails_when=anyone can create an account, or the redirect points to the old login URL;
        no_claim=admin-created accounts (still possible on purpose)."""
        self.assertContains(self.client.get("/accounts/signup/"), "closed", status_code=200)
        response = self.client.get("/account/")
        self.assertEqual(response["Location"], "/accounts/login/?next=/account/")


class InviteTests(TestCase):
    def setUp(self):
        self.inviter = make_user("aquiles", "aq@example.com")
        self.trip = Trip.objects.create(title="Sri Lanka", start_date=date(2026, 12, 21),
                                        end_date=date(2027, 1, 10), created_by=self.inviter)
        self.trip.travellers.add(self.inviter)
        self.client.force_login(self.inviter)

    def send(self, email, trip=None):
        return self.client.post("/invites/", {"email": email, "trip": trip.pk if trip else ""})

    def test_invite_to_trip_and_accept(self):
        """protects=AC16.1,4: invite email → anonymous link → name + password → member of the trip, logged in;
        fails_when=the account isn't created, isn't a member, can't log in by email, or a weak password passes;
        no_claim=the email's look in real mail clients."""
        self.send("Marta@Example.com", self.trip)
        invite = Invite.objects.get()
        self.assertEqual(invite.email, "marta@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"/invite/{invite.token}/", mail.outbox[0].body)

        self.client.logout()
        url = f"/invite/{invite.token}/"
        self.assertContains(self.client.get(url), "marta@example.com")
        weak = self.client.post(url, {"first_name": "Marta", "password1": "123", "password2": "123"})
        self.assertEqual(weak.status_code, 200)
        self.assertFalse(User.objects.filter(email="marta@example.com").exists())
        response = self.client.post(url, {"first_name": "Marta", "last_name": "Ruiz",
                                          "password1": "Tea-Hills-2026", "password2": "Tea-Hills-2026"})
        self.assertRedirects(response, f"/trips/{self.trip.pk}/", fetch_redirect_response=False)
        marta = User.objects.get(email="marta@example.com")
        self.assertEqual(marta.username, "marta-ruiz")
        self.assertIn(marta, self.trip.travellers.all())
        invite.refresh_from_db()
        self.assertEqual(invite.accepted_by, marta)
        self.client.logout()
        login = self.client.post("/accounts/login/", {"login": "marta@example.com", "password": "Tea-Hills-2026"})
        self.assertEqual(login.status_code, 302)

    def test_used_or_expired_links(self):
        """protects=AC16.2: a used or expired link shows the friendly page and creates nothing;
        fails_when=a second account is created or the link works after 14 days;
        no_claim=clock skew between servers."""
        self.send("marta@example.com", self.trip)
        invite = Invite.objects.get()
        self.client.logout()
        data = {"first_name": "Marta", "password1": "Tea-Hills-2026", "password2": "Tea-Hills-2026"}
        self.client.post(f"/invite/{invite.token}/", data)
        self.client.logout()
        again = self.client.post(f"/invite/{invite.token}/", data)
        self.assertContains(again, "no longer valid", status_code=404)
        self.assertEqual(User.objects.filter(email="marta@example.com").count(), 1)

        self.client.force_login(self.inviter)
        self.send("joost@example.com")
        late = Invite.objects.get(email="joost@example.com")
        Invite.objects.filter(pk=late.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.client.logout()
        self.assertContains(self.client.get(f"/invite/{late.token}/"), "no longer valid", status_code=404)

    def test_existing_user_added_directly(self):
        """protects=AC16.3: inviting an existing user's email to a trip adds them, no invite link;
        fails_when=a duplicate account invite is created or they aren't added;
        no_claim=inviting yourself (adds nothing new)."""
        partner = make_user("partner", "partner@example.com")
        response = self.send("partner@example.com", self.trip)
        self.assertRedirects(response, "/invites/", fetch_redirect_response=False)
        self.assertIn(partner, self.trip.travellers.all())
        self.assertFalse(Invite.objects.exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("added you", mail.outbox[0].subject)

    def test_only_own_trips_and_revoke(self):
        """protects=you can only invite into trips you're a member of; revoking kills the link;
        fails_when=a crafted POST invites into someone else's trip or a revoked link still works;
        no_claim=bulk invites."""
        other = Trip.objects.create(title="Not mine", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
                                    created_by=self.inviter)
        response = self.send("x@example.com", other)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invite.objects.exists())
        self.send("x@example.com")
        invite = Invite.objects.get()
        self.client.post(f"/invites/{invite.pk}/revoke/")
        self.client.logout()
        self.assertEqual(self.client.get(f"/invite/{invite.token}/").status_code, 404)
