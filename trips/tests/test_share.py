"""Issue 06: public share page."""

from trips.models import Entry, Media

from .helpers import MediaRootTestCase


class SharePageTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()
        self.public = Entry.objects.create(trip=self.trip, author=self.user, body="Elephants at Minneriya",
                                           occurred_at="2026-12-22T10:00Z")
        self.private = Entry.objects.create(trip=self.trip, author=self.user, body="Tummy trouble",
                                            occurred_at="2026-12-23T10:00Z", is_public=False)
        self.public_media = self.add_media(self.public)
        self.private_media = self.add_media(self.private)

    def add_media(self, entry):
        media = Media.objects.create(entry=entry, kind=Media.PHOTO, sha256=str(entry.pk), size_bytes=1,
                                     status=Media.READY, derivatives={"md": f"derived/{entry.pk}_md.webp"})
        media.original.name = f"originals/{entry.pk}.jpg"
        media.save()
        return media

    def url(self, suffix=""):
        return f"/s/{self.trip.share_token}/{suffix}"

    def test_public_entries_only(self):
        """protects=AC6: anonymous visitors see public entries only;
        fails_when=a private entry's text or media appears on the share page;
        no_claim=entries hidden by chapter (not a feature)."""
        response = self.client.get(self.url())
        self.assertContains(response, "Elephants at Minneriya")
        self.assertNotContains(response, "Tummy trouble")
        self.assertContains(response, f"/s/{self.trip.share_token}/m/{self.public_media.pk}/md/")
        self.assertNotContains(response, f"/m/{self.private_media.pk}/")
        self.assertContains(response, 'name="robots" content="noindex, nofollow"')
        self.assertNotContains(response, "Edit")

    def test_private_media_404_with_token(self):
        """protects=AC6: a private entry's media 404s even with a valid token and guessed id;
        fails_when=the token grants access to every media item of the trip;
        no_claim=nginx caching (responses are Cache-Control: private)."""
        ok = self.client.get(self.url(f"m/{self.public_media.pk}/md/"))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok["X-Accel-Redirect"], f"/protected/derived/{self.public.pk}_md.webp")
        self.assertEqual(self.client.get(self.url(f"m/{self.private_media.pk}/md/")).status_code, 404)
        self.assertEqual(self.client.get(self.url(f"m/{self.private_media.pk}/original/")).status_code, 404)

    def test_disabled_and_regenerated_links_die(self):
        """protects=AC6: turning sharing off or regenerating the token kills the old link;
        fails_when=the old URL still shows the trip or its media;
        no_claim=copies people already downloaded."""
        old = self.trip.share_token
        self.client.force_login(self.user)
        self.client.post(f"/trips/{self.trip.pk}/share/regenerate/")
        self.client.logout()
        self.assertEqual(self.client.get(f"/s/{old}/").status_code, 404)
        self.assertEqual(self.client.get(f"/s/{old}/m/{self.public_media.pk}/md/").status_code, 404)
        self.trip.refresh_from_db()
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.trip.share_enabled = False
        self.trip.save()
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/share/{self.trip.share_token}/map").status_code, 404)

    def test_unknown_token(self):
        """protects=random tokens reveal nothing;
        fails_when=an unknown token returns 200 or a redirect to login (leaks that the route exists);
        no_claim=rate limiting of guesses (token has 128 bits)."""
        self.assertEqual(self.client.get("/s/not-a-token/").status_code, 404)
