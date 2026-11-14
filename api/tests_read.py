"""Read API (v4 #23)."""

from datetime import date, timedelta

from django.test import Client
from django.utils import timezone

from api.tests import ApiTestCase
from trips.models import Chapter, Entry, Media, Trip


class ReadTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        self.trip = Trip.objects.create(title="Now", start_date=today - timedelta(days=2),
                                        end_date=today + timedelta(days=5), timezone="Europe/Amsterdam",
                                        created_by=self.user)
        self.trip.travellers.add(self.user)
        self.old = Trip.objects.create(title="Then", start_date=date(2020, 1, 1), end_date=date(2020, 1, 9),
                                       created_by=self.user)
        self.old.travellers.add(self.user)
        self.hidden = Trip.objects.create(title="Not mine", start_date=date(2020, 1, 1),
                                          end_date=date(2020, 1, 9), created_by=self.user)
        self.chapter = Chapter.objects.create(trip=self.trip, title="Coast", position=0)
        self.entries = [Entry.objects.create(trip=self.trip, author=self.user, body=f"**Day {i}**",
                                             occurred_at=timezone.now() - timedelta(hours=i))
                        for i in range(5)]
        self.photo = Media.objects.create(entry=self.entries[0], kind=Media.PHOTO, sha256="a" * 64,
                                          size_bytes=10, status=Media.READY, derivatives={"sm": "s.webp"},
                                          original="originals/a.jpg")
        self.tok = self.token()

    def get(self, path):
        return self.api("get", path, token=self.tok)

    def test_trips_list_marks_current(self):
        items = self.get("/trips").json()["items"]
        self.assertEqual([(t["title"], t["current"]) for t in items], [("Now", True), ("Then", False)])

    def test_trip_detail(self):
        body = self.get(f"/trips/{self.trip.pk}").json()
        self.assertEqual(body["chapters"], [{"id": self.chapter.pk, "title": "Coast", "position": 0}])
        self.assertEqual(body["travellers"][0]["name"], "Aquiles")
        self.assertEqual(body["live_share"], "members")

    def test_non_members_get_404_everywhere(self):
        for path in (f"/trips/{self.hidden.pk}", f"/trips/{self.hidden.pk}/entries",
                     f"/trips/{self.hidden.pk}/map", f"/trips/{self.hidden.pk}/live",
                     f"/trips/{self.hidden.pk}/positions"):
            with self.subTest(path=path):
                self.assertError(self.get(path), 404, "not_found")
        self.trip.travellers.remove(self.user)
        self.assertError(self.get(f"/entries/{self.entries[0].pk}"), 404, "not_found")
        self.assertError(self.get(f"/media/{self.photo.pk}/sm"), 404, "not_found")

    def test_entries_render_markdown_and_media(self):
        body = self.get(f"/entries/{self.entries[0].pk}").json()
        self.assertEqual(body["body_html"], "<p><strong>Day 0</strong></p>")
        self.assertEqual(body["media"][0]["urls"], {"original": f"/api/v1/media/{self.photo.pk}/original",
                                                    "sm": f"/api/v1/media/{self.photo.pk}/sm"})

    def test_paging(self):
        first = self.get(f"/trips/{self.trip.pk}/entries?limit=3").json()
        self.assertEqual(len(first["items"]), 3)
        rest = self.get(f"/trips/{self.trip.pk}/entries?limit=3&cursor={first['next_cursor']}").json()
        self.assertEqual(len(rest["items"]), 2)
        self.assertIsNone(rest["next_cursor"])
        ids = [e["id"] for e in first["items"] + rest["items"]]
        self.assertEqual(sorted(ids), sorted(e.pk for e in self.entries))

    def test_updated_since_returns_changes_and_deletions(self):
        mark = timezone.now()
        changed, gone = self.entries[1], self.entries[2]
        changed.body = "edited"
        changed.save()
        gone_id = gone.pk
        gone.delete()
        self.photo.status = Media.FAILED
        self.photo.save()  # a media change counts as a change of its entry
        since = mark.isoformat().replace("+", "%2B")
        body = self.get(f"/trips/{self.trip.pk}/entries?updated_since={since}").json()
        self.assertEqual({e["id"] for e in body["items"]}, {changed.pk, self.entries[0].pk})
        self.assertEqual(body["deleted"], [gone_id])

    def test_media_file_needs_membership(self):
        response = self.get(f"/media/{self.photo.pk}/sm")
        self.assertIn(response.status_code, (200, 404))  # 404 only because the test file isn't on disk
        self.assertNotEqual(Client().get(f"/api/v1/media/{self.photo.pk}/sm").status_code, 200)

    def test_old_map_urls_redirect(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/trips/{self.trip.pk}/map.json")
        self.assertRedirects(response, f"/api/v1/trips/{self.trip.pk}/map", status_code=301,
                             fetch_redirect_response=False)
        response = Client().get(f"/s/{self.trip.share_token}/map.json")
        self.assertRedirects(response, f"/api/v1/share/{self.trip.share_token}/map", status_code=301,
                             fetch_redirect_response=False)

    def test_pages_use_the_api(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(f"/trips/{self.trip.pk}/"), f'data-url="/api/v1/trips/{self.trip.pk}/map"')
        self.assertContains(Client().get(f"/s/{self.trip.share_token}/"),
                            f'data-url="/api/v1/share/{self.trip.share_token}/map"')
