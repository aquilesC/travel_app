"""Issue 08: subscriptions and the daily digest."""

from datetime import timedelta

from django.core import mail
from django.utils import timezone

from trips.digest import send_digests
from trips.models import Entry, Subscriber

from .helpers import MediaRootTestCase


class DigestTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()

    def subscribe(self, email="mum@example.com"):
        response = self.client.post(f"/s/{self.trip.share_token}/subscribe/", {"email": email})
        self.assertContains(response, "Check your inbox")
        return Subscriber.objects.get(email=email)

    def confirm(self, subscriber):
        self.client.get(f"/subscribe/confirm/{subscriber.token}/")
        subscriber.refresh_from_db()
        return subscriber

    def add_entry(self, body, public=True, created=None):
        entry = Entry.objects.create(trip=self.trip, author=self.user, occurred_at=timezone.now(),
                                     body=body, is_public=public)
        if created:
            Entry.objects.filter(pk=entry.pk).update(created_at=created)
        return entry

    def test_double_opt_in(self):
        """protects=AC11: subscribers get a confirmation email and nothing else until they confirm;
        fails_when=an unconfirmed address receives a digest;
        no_claim=Mailgun delivery (locmem backend here)."""
        subscriber = self.subscribe()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"/subscribe/confirm/{subscriber.token}/", mail.outbox[0].body)
        self.add_entry("Arrived!")
        mail.outbox.clear()
        self.assertEqual(send_digests(), 0)
        self.assertEqual(mail.outbox, [])

    def test_one_digest_per_day_with_new_public_entries(self):
        """protects=AC11: one email with new public entries; none on quiet days; private never;
        fails_when=entries are repeated in the next digest, private text is emailed, or empty digests go out;
        no_claim=the 20:00 timing (scheduler test) or email rendering in real clients."""
        subscriber = self.confirm(self.subscribe())
        mail.outbox.clear()
        self.add_entry("Elephants!")
        self.add_entry("Secret", public=False)
        self.assertEqual(send_digests(), 1)
        message = mail.outbox[0]
        self.assertIn("Elephants!", message.body)
        self.assertNotIn("Secret", message.body)
        self.assertIn(f"/subscribe/unsubscribe/{subscriber.token}/", message.extra_headers["List-Unsubscribe"])
        self.assertEqual(message.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn("text/html", message.alternatives[0].mimetype)

        mail.outbox.clear()
        self.assertEqual(send_digests(timezone.now() + timedelta(days=1)), 0)  # quiet day
        self.assertEqual(mail.outbox, [])

    def test_unsubscribe_get_shows_button_post_unsubscribes(self):
        """protects=AC11: no email after unsubscribing; link prefetchers can't unsubscribe by GET;
        fails_when=GET unsubscribes or POST (incl. one-click without CSRF) doesn't;
        no_claim=Gmail's one-click implementation details."""
        subscriber = self.confirm(self.subscribe())
        page = self.client.get(f"/subscribe/unsubscribe/{subscriber.token}/")
        self.assertContains(page, "Unsubscribe")
        subscriber.refresh_from_db()
        self.assertIsNone(subscriber.unsubscribed_at)
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.post(f"/subscribe/unsubscribe/{subscriber.token}/", {"List-Unsubscribe": "One-Click"})
        subscriber.refresh_from_db()
        self.assertIsNotNone(subscriber.unsubscribed_at)
        self.add_entry("After")
        mail.outbox.clear()
        self.assertEqual(send_digests(), 0)

    def test_unconfirmed_expire_and_resubscribe(self):
        """protects=unconfirmed signups vanish after 7 days; resubscribing after unsubscribe re-confirms;
        fails_when=stale rows linger forever or a returning subscriber skips confirmation;
        no_claim=bounce handling (Mailgun side)."""
        stale = self.subscribe("old@example.com")
        Subscriber.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(days=8))
        send_digests()
        self.assertFalse(Subscriber.objects.filter(pk=stale.pk).exists())

        subscriber = self.confirm(self.subscribe())
        self.client.post(f"/subscribe/unsubscribe/{subscriber.token}/")
        mail.outbox.clear()
        subscriber = self.subscribe()
        self.assertIsNone(subscriber.confirmed_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_bad_email_and_honeypot(self):
        """protects=invalid addresses and bot submissions create nothing;
        fails_when=garbage rows or confirmation emails are created;
        no_claim=sophisticated bots that skip hidden fields."""
        response = self.client.post(f"/s/{self.trip.share_token}/subscribe/", {"email": "nope"})
        self.assertEqual(response.status_code, 400)
        self.client.post(f"/s/{self.trip.share_token}/subscribe/", {"email": "bot@example.com", "website": "x"})
        self.assertFalse(Subscriber.objects.exists())
        self.assertEqual(mail.outbox, [])
