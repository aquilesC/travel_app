"""Issues 09 (account page) and 10 (public profile)."""

import shutil
import tempfile
from datetime import date
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from pillow_heif import register_heif_opener

from trips.models import Entry, Track, Trip
from trips.tests.test_gpx import make_gpx

register_heif_opener()


class MediaRootMixin:
    def setUp(self):
        super().setUp()
        self.media_root = Path(tempfile.mkdtemp())
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.user = get_user_model().objects.create_user("aquiles", password="old-Secret-1")
        self.client.force_login(self.user)


def heic_upload(size=(3000, 2000)):
    buffer = BytesIO()
    Image.new("RGB", size, "teal").save(buffer, format="HEIF")
    return SimpleUploadedFile("me.HEIC", buffer.getvalue(), "image/heic")


def account_post(**extra):
    return {"first_name": "Aquiles", "last_name": "C", "email": "a@example.com",
            "whatsapp_number": "", "is_public": "on", **extra}


class AccountPageTests(MediaRootMixin, TestCase):
    def test_save_name_and_bad_whatsapp(self):
        """protects=AC9.1: name/email save; a malformed WhatsApp number shows a field error;
        fails_when=the name isn't saved or a bad number is stored;
        no_claim=email verification (none in v2)."""
        self.client.post("/account/", account_post())
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), "Aquiles C")
        response = self.client.post("/account/", account_post(whatsapp_number="0612"))
        self.assertContains(response, "international format")
        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.whatsapp_number)

    def test_heic_avatar_replaces_previous(self):
        """protects=AC9.2: a HEIC becomes a 512×512 WebP; the old avatar file is deleted;
        fails_when=wrong size/format or orphaned files pile up;
        no_claim=face-aware cropping (centre crop)."""
        self.client.post("/account/", {**account_post(), "picture": heic_upload()})
        first = self.user.profile.__class__.objects.get(user=self.user).avatar
        self.assertEqual(Image.open(self.media_root / first).size, (512, 512))
        self.assertEqual(Image.open(self.media_root / first).format, "WEBP")
        self.client.post("/account/", {**account_post(), "picture": heic_upload((800, 1200))})
        second = self.user.profile.__class__.objects.get(user=self.user).avatar
        self.assertNotEqual(first, second)
        self.assertFalse((self.media_root / first).exists())
        self.client.post("/account/picture/remove/")
        self.assertFalse((self.media_root / second).exists())

    def test_non_image_rejected(self):
        """protects=AC9.3: a non-image picture upload is refused and nothing is stored;
        fails_when=it crashes (500) or saves a broken avatar;
        no_claim=malicious image payloads (Pillow's decoder is trusted)."""
        bogus = SimpleUploadedFile("me.jpg", b"not really a jpeg", "image/jpeg")
        response = self.client.post("/account/", {**account_post(), "picture": bogus})
        self.assertContains(response, "not a picture we can read")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.avatar, "")

    def test_password_change(self):
        """protects=AC9.4: wrong old password fails; right one works and keeps the session;
        fails_when=the password changes without the old one, or the user is logged out;
        no_claim=password reset by email (not offered)."""
        bad = self.client.post("/accounts/password_change/", {
            "old_password": "nope", "new_password1": "Fresh-Pass-2026", "new_password2": "Fresh-Pass-2026"})
        self.assertEqual(bad.status_code, 200)
        good = self.client.post("/accounts/password_change/", {
            "old_password": "old-Secret-1", "new_password1": "Fresh-Pass-2026", "new_password2": "Fresh-Pass-2026"})
        self.assertRedirects(good, "/accounts/password_change/done/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Fresh-Pass-2026"))
        self.assertEqual(self.client.get("/account/").status_code, 200)  # still logged in


class PublicProfileTests(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.partner = get_user_model().objects.create_user("partner", password="x")

    def trip(self, title, travellers, share=True):
        trip = Trip.objects.create(title=title, start_date=date(2026, 12, 21), end_date=date(2027, 1, 5),
                                   timezone="Asia/Colombo", created_by=self.user, share_enabled=share)
        trip.travellers.set(travellers)
        return trip

    def test_counts_km_and_listing(self):
        """protects=AC10.1-3: trips counted per traveller; km = GPX or check-in legs; only shared trips listed;
        fails_when=a trip the user didn't go on counts, km ignores one source, or a private trip is listed;
        no_claim=road distance (check-in legs are straight lines)."""
        gpx_trip = self.trip("Sailing", [self.user, self.partner])
        Track.objects.create(trip=gpx_trip, mode="sail", gpx_text=make_gpx(2000), uploaded_by=self.user)
        legs = self.trip("Weekend", [self.user], share=False)
        # Colombo -> Kandy ~ 94 km straight line
        Entry.objects.create(trip=legs, author=self.user, occurred_at="2026-12-21T10:00Z", latitude=6.9271, longitude=79.8612)
        Entry.objects.create(trip=legs, author=self.user, occurred_at="2026-12-22T10:00Z", latitude=7.2906, longitude=80.6337, is_public=False)
        self.trip("Partner only", [self.partner])

        from trips.gpx import track_summary
        from trips.stats import haversine_km
        gpx_km = track_summary(gpx_trip.tracks.get())["stats"]["distance_km"]
        legs_km = haversine_km((6.9271, 79.8612), (7.2906, 80.6337))
        self.assertAlmostEqual(legs_km, 94, delta=2)  # sanity: Colombo-Kandy straight line
        self.client.logout()
        page = self.client.get("/u/aquiles/")
        self.assertContains(page, "<strong>2</strong> trips")
        self.assertContains(page, f"<strong>{round(gpx_km + legs_km)}</strong> km")
        self.assertContains(page, f"/s/{gpx_trip.share_token}/")
        self.assertNotContains(page, legs.share_token)
        self.assertNotContains(page, "Partner only")
        self.assertContains(self.client.get("/u/partner/"), "<strong>2</strong> trips")

    def test_private_profile_hidden(self):
        """protects=AC10.4: a private profile and its avatar 404 for visitors;
        fails_when=anonymous visitors still see it;
        no_claim=search engines (pages are noindex too)."""
        self.client.post("/account/", {**account_post(is_public=""), "picture": heic_upload()})
        self.client.logout()
        self.assertEqual(self.client.get("/u/aquiles/").status_code, 404)
        self.assertEqual(self.client.get("/u/aquiles/avatar/").status_code, 404)
        self.assertEqual(self.client.get("/u/nobody/").status_code, 404)
        self.client.force_login(self.partner)
        self.assertEqual(self.client.get("/u/aquiles/").status_code, 200)
