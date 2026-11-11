"""Issue 03: trips, chapters, entries and their editor."""

from datetime import date, datetime, timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from trips.models import Chapter, Entry, Trip
from trips.templatetags.trips_tags import render_markdown
from trips.timeline import build_timeline

from .helpers import MediaRootTestCase


class TripModelTests(MediaRootTestCase):
    def test_end_before_start_rejected(self):
        """protects=AC2b: a trip can't end before it starts (form and database);
        fails_when=either the form validation or the DB constraint lets it through;
        no_claim=date pickers in the browser."""
        trip = Trip(title="x", start_date=date(2026, 12, 21), end_date=date(2026, 12, 1),
                    created_by=self.user)
        with self.assertRaises(ValidationError):
            trip.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            trip.save()

    def test_form_rejects_end_before_start(self):
        """protects=the web form shows the date error instead of crashing;
        fails_when=the POST returns 500 or creates the trip;
        no_claim=wording of the message."""
        self.client.force_login(self.user)
        response = self.client.post("/trips/new/", {
            "title": "Bad", "start_date": "2026-12-21", "end_date": "2026-12-01",
            "timezone": "Asia/Colombo",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Trip.objects.filter(title="Bad").exists())

    def test_create_trip_with_new_companions(self):
        """protects=trips are created from the web with companions added by name;
        fails_when=new names aren't created/linked or the creator isn't recorded;
        no_claim=companion editing UI layout."""
        self.client.force_login(self.user)
        response = self.client.post("/trips/new/", {
            "title": "Sri Lanka", "start_date": "2026-12-21", "end_date": "2027-01-10",
            "timezone": "Asia/Colombo", "new_companions": "Marta, Joost", "share_enabled": "on",
            "travellers": [self.user.pk],
        })
        trip = Trip.objects.get(title="Sri Lanka")
        self.assertRedirects(response, f"/trips/{trip.pk}/")
        self.assertEqual(sorted(p.name for p in trip.companions.all()), ["Joost", "Marta"])
        self.assertEqual(trip.created_by, self.user)


class EntryTimezoneTests(MediaRootTestCase):
    def test_entry_time_entered_and_shown_in_trip_zone(self):
        """protects=AC2b: 18:00 typed in an Asia/Colombo trip is 12:30 UTC and shows as 18:00;
        fails_when=times are read or displayed in the server zone (Europe/Amsterdam) or UTC;
        no_claim=multi-zone trips (out of scope)."""
        trip = self.make_trip()
        self.client.force_login(self.user)
        response = self.client.post(f"/trips/{trip.pk}/entries/new/", {
            "occurred_at": "2026-12-22T18:00", "body": "Sunset at Galle fort", "is_public": "on",
        })
        entry = Entry.objects.get(trip=trip)
        self.assertRedirects(response, f"/entries/{entry.pk}/edit/")
        self.assertEqual(entry.occurred_at, datetime(2026, 12, 22, 12, 30, tzinfo=dt_timezone.utc))
        page = self.client.get(f"/trips/{trip.pk}/").content.decode()
        self.assertIn("Tue 22 Dec 2026, 18:00", page)
        edit = self.client.get(f"/entries/{entry.pk}/edit/").content.decode()
        self.assertIn('value="2026-12-22T18:00"', edit)

    def test_preview_does_not_save(self):
        """protects=the Preview button renders markdown without saving;
        fails_when=preview creates an entry or shows raw markdown;
        no_claim=preview styling."""
        trip = self.make_trip()
        self.client.force_login(self.user)
        response = self.client.post(f"/trips/{trip.pk}/entries/new/", {
            "occurred_at": "2026-12-22T18:00", "body": "**big**", "preview": "1",
        })
        self.assertContains(response, "<strong>big</strong>")
        self.assertFalse(Entry.objects.exists())


class MarkdownTests(MediaRootTestCase):
    def test_script_stripped(self):
        """protects=AC2b: entry markdown can't inject scripts into share pages;
        fails_when=<script>, onerror handlers or javascript: links survive rendering;
        no_claim=every possible XSS vector (nh3's allowlist is trusted)."""
        html = render_markdown(
            "Hi <script>alert(1)</script> <img src=x onerror=alert(2)> [x](javascript:alert(3)) **ok**"
        )
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("<strong>ok</strong>", html)


class ChapterTests(MediaRootTestCase):
    def test_create_and_reorder(self):
        """protects=chapters keep a stable order and can be swapped;
        fails_when=moving violates the unique position constraint or does nothing;
        no_claim=drag-and-drop (not offered)."""
        trip = self.make_trip()
        self.client.force_login(self.user)
        for title in ["Colombo", "Kandy", "Galle"]:
            self.client.post(f"/trips/{trip.pk}/chapters/new/", {"title": title})
        self.assertEqual([c.title for c in trip.chapters.all()], ["Colombo", "Kandy", "Galle"])
        galle = Chapter.objects.get(title="Galle")
        self.client.post(f"/chapters/{galle.pk}/move/up/")
        self.assertEqual([c.title for c in trip.chapters.all()], ["Colombo", "Galle", "Kandy"])
        colombo = Chapter.objects.get(title="Colombo")
        self.client.post(f"/chapters/{colombo.pk}/move/up/")  # already first: no-op
        self.assertEqual([c.title for c in trip.chapters.all()], ["Colombo", "Galle", "Kandy"])

    def test_timeline_groups_by_chapter(self):
        """protects=entries show under their chapter, chapterless ones first, by time;
        fails_when=entries land in the wrong group or order;
        no_claim=template markup."""
        trip = self.make_trip()
        kandy = Chapter.objects.create(trip=trip, title="Kandy", position=0)
        late = Entry.objects.create(trip=trip, author=self.user, chapter=kandy,
                                    occurred_at="2026-12-25T10:00Z")
        early = Entry.objects.create(trip=trip, author=self.user, chapter=kandy,
                                     occurred_at="2026-12-24T10:00Z")
        loose = Entry.objects.create(trip=trip, author=self.user, occurred_at="2026-12-21T10:00Z",
                                     is_public=False)
        timeline = build_timeline(trip)
        self.assertEqual([(s.chapter, [e.pk for e in s.entries]) for s in timeline],
                         [(None, [loose.pk]), (kandy, [early.pk, late.pk])])
        public = build_timeline(trip, public_only=True)
        self.assertEqual([(s.chapter, [e.pk for e in s.entries]) for s in public], [(kandy, [early.pk, late.pk])])

    def test_entry_chapter_must_belong_to_trip(self):
        """protects=an entry can't be filed under another trip's chapter;
        fails_when=a crafted POST attaches a foreign chapter;
        no_claim=admin edits."""
        trip, other = self.make_trip(), self.make_trip(title="Other")
        foreign = Chapter.objects.create(trip=other, title="Elsewhere", position=0)
        self.client.force_login(self.user)
        response = self.client.post(f"/trips/{trip.pk}/entries/new/", {
            "occurred_at": "2026-12-22T18:00", "chapter": foreign.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Entry.objects.exists())
