"""Issue 07: WhatsApp ingest via Twilio (Twilio HTTP calls mocked)."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import BytesIO
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from PIL import Image

from trips.models import Chapter, Entry, InboundMessage, Media, Trip
from trips.whatsapp import active_trip, parse_commands, twilio_signature

from .helpers import MediaRootTestCase

TOKEN = "test-auth-token"
HOOK = "https://trips.example/hooks/twilio/whatsapp/"
NUMBER = "+31600000001"


def jpeg_bytes():
    buffer = BytesIO()
    Image.new("RGB", (80, 60), "red").save(buffer, "JPEG")
    return buffer.getvalue()


def fake_download(url, target, max_bytes=None):
    target.write_bytes(jpeg_bytes() + url.encode())  # unique per URL
    return target.stat().st_size


@override_settings(TWILIO_AUTH_TOKEN=TOKEN, TWILIO_WEBHOOK_URL=HOOK, TWILIO_ACCOUNT_SID="AC1",
                   TWILIO_WHATSAPP_FROM="whatsapp:+14155238886", SITE_URL="https://trips.example")
class WhatsAppTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.user.profile.whatsapp_number = NUMBER
        self.user.profile.save()
        self.trip = Trip.objects.create(title="Sri Lanka", start_date=date.today() - timedelta(days=2),
                                        end_date=date.today() + timedelta(days=10),
                                        timezone="Asia/Colombo", created_by=self.user)
        self.trip.travellers.add(self.user)
        self.sent = []
        patches = [
            mock.patch("trips.whatsapp.send_whatsapp", side_effect=lambda to, body: self.sent.append((to, body))),
            mock.patch("trips.whatsapp.download_media", side_effect=fake_download),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.counter = 0

    def post(self, sign=True, sid=None, **fields):
        self.counter += 1
        data = {"MessageSid": sid or f"SM{self.counter:04d}", "From": f"whatsapp:{NUMBER}",
                "To": "whatsapp:+14155238886", "Body": "", "NumMedia": "0", **fields}
        headers = {"HTTP_X_TWILIO_SIGNATURE": twilio_signature(HOOK, data, TOKEN) if sign else "bad"}
        return self.client.post("/hooks/twilio/whatsapp/", data, **headers)

    def photos(self, count, caption=""):
        fields = {"NumMedia": str(count), "Body": caption}
        for i in range(count):
            fields[f"MediaUrl{i}"] = f"https://api.twilio.com/media/{self.counter}-{i}"
            fields[f"MediaContentType{i}"] = "image/jpeg"
        return fields

    def test_invalid_signature_rejected(self):
        """protects=AC7: unsigned or wrongly signed requests are refused and stored nowhere;
        fails_when=a forged POST creates a message or entry;
        no_claim=Twilio's real signature on our public URL (checked in the field test)."""
        response = self.post(sign=False, Body="forged")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(InboundMessage.objects.exists())

    def test_replayed_sid_is_idempotent(self):
        """protects=AC7: Twilio retries with the same MessageSid create no duplicate entry;
        fails_when=the same message is processed twice;
        no_claim=two different messages with the same text (they are separate)."""
        self.assertEqual(self.post(sid="SMdup", Body="hello").status_code, 200)
        self.assertEqual(self.post(sid="SMdup", Body="hello").status_code, 200)
        self.assertEqual(InboundMessage.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Entry.objects.get().body, "hello")

    def test_unknown_number_ignored(self):
        """protects=AC8: only our two numbers can post;
        fails_when=a stranger's message creates an entry or gets a reply;
        no_claim=spoofed numbers (Twilio signature covers From)."""
        data = {"From": "whatsapp:+31699999999", "Body": "spam"}
        self.post(**data)
        self.assertFalse(Entry.objects.exists())
        self.assertEqual(InboundMessage.objects.get().status, InboundMessage.REJECTED)
        self.assertEqual(self.sent, [])

    def test_photo_burst_and_commands(self):
        """protects=AC9: 5 photos + caption in a burst = 1 entry, 1 reply; #new and #chapter work;
        fails_when=each photo makes its own entry, replies repeat, or commands are stored as text;
        no_claim=real Twilio media downloads (mocked)."""
        self.post(**self.photos(1, "Train to Ella"))
        for _ in range(4):
            self.post(**self.photos(1))
        entry = Entry.objects.get()
        self.assertEqual(entry.body, "Train to Ella")
        self.assertEqual(entry.media.count(), 5)
        self.assertTrue(all(m.is_travel_copy and m.status == Media.READY for m in entry.media.all()))
        self.assertEqual(len(self.sent), 1)
        self.assertIn(f"/entries/{entry.pk}/edit/", self.sent[0][1])

        self.post(Body="#new Tea plantation")
        self.assertEqual(Entry.objects.count(), 2)
        self.assertEqual(Entry.objects.latest("id").body, "Tea plantation")

        self.post(Body="#chapter Galle")
        galle = Chapter.objects.get(title="Galle")
        self.assertEqual(Entry.objects.count(), 2)  # bare command makes no entry
        self.assertIn("Galle", self.sent[-1][1])
        self.post(Body="Fort walls at sunset")
        newest = Entry.objects.latest("id")
        self.assertEqual((newest.chapter, newest.body), (galle, "Fort walls at sunset"))

    def test_grouping_window(self):
        """protects=messages more than 10 minutes apart become separate entries;
        fails_when=a message hours later is appended to an old entry;
        no_claim=exact boundary at 10:00.000."""
        self.post(Body="Breakfast")
        InboundMessage.objects.update(received_at=timezone.now() - timedelta(minutes=30))
        Entry.objects.update(occurred_at=timezone.now() - timedelta(minutes=30))
        self.post(Body="Lunch")
        self.assertEqual(Entry.objects.count(), 2)

    def test_location_and_private(self):
        """protects=a shared location becomes a check-in; a second location starts a new one; #private hides;
        fails_when=locations overwrite each other or #private text is published;
        no_claim=live-location sharing (Twilio sends static pins only)."""
        self.post(Latitude="7.2906", Longitude="80.6337", Label="Temple of the Tooth")
        self.post(Latitude="7.3", Longitude="80.64", Address="Kandy Lake")
        first, second = Entry.objects.order_by("id")
        self.assertEqual((first.place_name, str(first.latitude)), ("Temple of the Tooth", "7.290600"))
        self.assertEqual(second.place_name, "Kandy Lake")
        self.post(Body="#private note to self")
        second.refresh_from_db()
        self.assertFalse(second.is_public)
        self.assertIn("note to self", second.body)

    def test_unrouted_then_assigned(self):
        """protects=AC10: a message with no active trip is kept as unrouted and can be assigned later;
        fails_when=it's dropped, or assignment doesn't create the entry;
        no_claim=bulk assignment of many messages at once."""
        self.trip.start_date = date.today() + timedelta(days=30)
        self.trip.end_date = date.today() + timedelta(days=40)
        self.trip.save()
        self.post(Body="Packing!")
        message = InboundMessage.objects.get()
        self.assertEqual(message.status, InboundMessage.UNROUTED)
        self.assertFalse(Entry.objects.exists())
        self.assertIn("No trip is active", self.sent[0][1])

        self.client.force_login(self.user)
        self.assertContains(self.client.get("/"), "Packing!")
        self.client.post(f"/inbound/{message.pk}/assign/", {"trip": self.trip.pk})
        message.refresh_from_db()
        self.assertEqual(message.status, InboundMessage.PROCESSED)
        self.assertEqual(message.entry.body, "Packing!")
        self.assertEqual(message.entry.trip, self.trip)


class RoutingUnitTests(MediaRootTestCase):
    def test_active_trip_uses_trip_timezone(self):
        """protects=routing uses the trip's local date, latest start wins on overlap;
        fails_when=a Colombo-evening message at 19:00 UTC on the eve of the trip lands nowhere;
        no_claim=trips spanning date-line jumps."""
        colombo = self.make_trip(start_date=date(2026, 12, 21), end_date=date(2027, 1, 10))
        # 2026-12-20 19:00 UTC = 2026-12-21 00:30 in Colombo -> trip day 1.
        self.assertEqual(active_trip(datetime(2026, 12, 20, 19, 0, tzinfo=dt_timezone.utc), self.user), colombo)
        self.assertIsNone(active_trip(datetime(2026, 12, 20, 18, 0, tzinfo=dt_timezone.utc), self.user))
        weekend = self.make_trip(title="Side trip", start_date=date(2026, 12, 26), end_date=date(2026, 12, 28))
        self.assertEqual(active_trip(datetime(2026, 12, 27, 6, 0, tzinfo=dt_timezone.utc), self.user), weekend)

    def test_parse_commands(self):
        """protects=commands are recognised only at the start and stripped from the text;
        fails_when='#chapter' mid-text triggers or the command word leaks into the entry;
        no_claim=commands in other languages."""
        self.assertEqual(parse_commands("#chapter Galle\nFirst day"), ("First day", "Galle", True, False))
        self.assertEqual(parse_commands("#NEW hi"), ("hi", None, True, False))
        self.assertEqual(parse_commands("#private"), ("", None, False, True))
        self.assertEqual(parse_commands("Loving #chapter books"), ("Loving #chapter books", None, False, False))
        self.assertEqual(parse_commands("#chapter"), ("#chapter", None, False, False))
