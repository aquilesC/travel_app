"""Issues 15 (membership), 17 (landing/404/500) and 18 (reader data)."""

from datetime import timedelta

from django.template.loader import get_template
from django.test import override_settings
from django.utils import timezone

from trips.gpx import map_data
from trips.models import Chapter, Entry, ImportBatch, Media, Track

from .helpers import MediaRootTestCase
from .test_gpx import make_gpx


class MembershipTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()  # member: self.user only
        self.entry = Entry.objects.create(trip=self.trip, author=self.user, occurred_at=timezone.now())
        self.media = Media.objects.create(entry=self.entry, kind=Media.PHOTO, sha256="x", size_bytes=1,
                                          status=Media.READY, derivatives={"md": "derived/x_md.webp"})
        self.chapter = Chapter.objects.create(trip=self.trip, title="Kandy", position=0)
        self.track = Track.objects.create(trip=self.trip, gpx_text=make_gpx(10), uploaded_by=self.user)
        self.batch = ImportBatch.objects.create(trip=self.trip, created_by=self.other_user)

    def test_non_member_gets_404_everywhere(self):
        """protects=AC15.1: someone else's trip is invisible: every page, file and API 404s;
        fails_when=any member-only URL answers 200/302 for a non-member;
        no_claim=admin access (staff see everything there by design)."""
        self.client.force_login(self.other_user)
        t, e, m = self.trip.pk, self.entry.pk, self.media.pk
        gets = [f"/trips/{t}/", f"/trips/{t}/edit/", f"/api/v1/trips/{t}/map", f"/trips/{t}/entries/new/",
                f"/entries/{e}/edit/", f"/entries/{e}/delete/", f"/api/v1/entries/{e}", f"/api/v1/media/{m}/md",
                f"/m/{m}/md/", f"/chapters/{self.chapter.pk}/edit/", f"/tracks/{self.track.pk}/edit/",
                f"/imports/{self.batch.pk}/review/"]
        for url in gets:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        posts = [f"/trips/{t}/import/", f"/trips/{t}/chapters/new/", f"/media-items/{m}/delete/",
                 f"/chapters/{self.chapter.pk}/move/up/", f"/trips/{t}/share/regenerate/"]
        for url in posts:
            self.assertEqual(self.client.post(url, {"title": "x"}).status_code, 404, url)
        response = self.client.post("/api/v1/uploads", {"filename": "a.jpg", "size": 3, "entry_id": e},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(self.client.get("/"), "Sri Lanka")
        self.assertTrue(Media.objects.filter(pk=m).exists())

    def test_member_sees_everything(self):
        """protects=members keep full access after the change;
        fails_when=the membership filter locks out a legitimate member;
        no_claim=every action (covered by the feature tests)."""
        self.trip.travellers.add(self.other_user)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(f"/trips/{self.trip.pk}/").status_code, 200)
        self.assertContains(self.client.get("/"), "Sri Lanka")

    def test_trip_needs_a_member_and_creator_joins(self):
        """protects=AC15.3: a trip can't be left without members; creating one makes you a member;
        fails_when=an empty member list saves or the creator can't see their new trip;
        no_claim=leaving a trip yourself (allowed while others remain)."""
        self.client.force_login(self.user)
        data = {"title": "Sri Lanka", "start_date": "2026-12-21", "end_date": "2027-01-10",
                "timezone": "Asia/Colombo"}
        response = self.client.post(f"/trips/{self.trip.pk}/edit/", data)
        self.assertContains(response, "at least one member")
        self.client.post("/trips/new/", {**data, "title": "Weekend", "travellers": [self.user.pk]})
        from trips.models import Trip
        self.assertIn(self.user, Trip.objects.get(title="Weekend").travellers.all())

    def test_member_choices_are_fellow_travellers(self):
        """protects=the member list doesn't expose every user of the platform;
        fails_when=a stranger appears as a choice in the trip form;
        no_claim=user search (not offered; invites cover new people)."""
        self.client.force_login(self.user)
        form = self.client.get(f"/trips/{self.trip.pk}/edit/").context["form"]
        self.assertEqual(list(form.fields["travellers"].queryset), [self.user])


class LandingAndErrorTests(MediaRootTestCase):
    def test_landing_for_visitors_trips_for_members(self):
        """protects=AC17.1: visitors see the landing page, members their trips;
        fails_when=/ redirects visitors to login or members see the landing page;
        no_claim=visual design (checked by eye)."""
        response = self.client.get("/")
        self.assertContains(response, "Every trip, told as it")
        self.assertContains(response, 'href="/accounts/login/"')
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/"), "Our trips")

    @override_settings(DEBUG=False)
    def test_custom_404_and_500(self):
        """protects=AC17.2-3: unknown URLs get the friendly 404; 500.html renders without context;
        fails_when=Django's bare 404 shows or 500.html needs a request;
        no_claim=nginx-level errors (502 when Django is down)."""
        response = self.client.get("/no/such/place/")
        self.assertContains(response, "This path isn't on the map", status_code=404)
        self.assertIn("bump in the road", get_template("500.html").render())


class ReaderDataTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()
        self.public = Entry.objects.create(trip=self.trip, author=self.user, occurred_at=timezone.now())
        self.private = Entry.objects.create(trip=self.trip, author=self.user, is_public=False,
                                            occurred_at=timezone.now() + timedelta(hours=1))
        self.photo = self.add_photo(self.public, 7.29, 80.63)
        self.secret = self.add_photo(self.private, 7.30, 80.64)

    def add_photo(self, entry, lat, lon):
        media = Media.objects.create(entry=entry, kind=Media.PHOTO, sha256=f"{lat}", size_bytes=1,
                                     status=Media.READY, latitude=lat, longitude=lon,
                                     derivatives={"sm": "s.webp", "md": "m.webp", "lg": "l.webp"})
        media.original.name = "o.jpg"
        media.save()
        return media

    def test_photo_features_respect_context(self):
        """protects=AC18.1: map.json has a photo feature per located photo, with a URL valid for the viewer;
        fails_when=the share map leaks a private photo or gives member-only thumbnail URLs;
        no_claim=map rendering in the browser."""
        self.client.force_login(self.user)
        member = self.client.get(f"/api/v1/trips/{self.trip.pk}/map").json()["features"]
        thumbs = {f["properties"]["media_id"]: f["properties"]["thumb"] for f in member if f["properties"]["kind"] == "photo"}
        self.assertEqual(thumbs, {self.photo.pk: f"/api/v1/media/{self.photo.pk}/sm",
                                  self.secret.pk: f"/api/v1/media/{self.secret.pk}/sm"})
        self.client.logout()
        shared = self.client.get(f"/api/v1/share/{self.trip.share_token}/map").json()["features"]
        thumbs = {f["properties"]["media_id"]: f["properties"]["thumb"] for f in shared if f["properties"]["kind"] == "photo"}
        self.assertEqual(thumbs, {self.photo.pk: f"/s/{self.trip.share_token}/m/{self.photo.pk}/sm/"})
        self.assertEqual(self.client.get(thumbs[self.photo.pk]).status_code, 200)

    def test_entries_carry_coordinates_and_viewer_items(self):
        """protects=AC18.2-3: entries carry map coordinates (photo fallback); photos link to full size without JS;
        fails_when=an entry located only by its photo has no data-lat, or photos aren't plain links;
        no_claim=the JavaScript behaviour itself (no browser in CI)."""
        self.client.force_login(self.user)
        page = self.client.get(f"/trips/{self.trip.pk}/").content.decode()
        self.assertIn(f'id="entry-{self.public.pk}"', page)
        self.assertIn('data-lat="7.290000" data-lon="80.630000"', page)
        self.assertIn(f'href="/m/{self.photo.pk}/lg/" class="lb-item"', page)
        self.assertIn('<dialog class="viewer"', page)
        self.assertEqual(map_data(self.trip, public_only=True)["features"][0]["properties"]["kind"], "entry")
