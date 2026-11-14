"""Service layer (v4 #20): membership rules and validation, independent of any view."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model

from trips.access import get_owned, get_trip
from trips.models import Chapter, Entry, Media, Track
from trips.services import chapters, entries, imports, media, tracks, trips
from trips.services.errors import Invalid, NotFound
from trips.tests.helpers import MediaRootTestCase
from trips.tests.test_gpx import make_gpx

WHEN = datetime(2026, 12, 23, 8, 0, tzinfo=dt_timezone.utc)


class ServiceTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()
        self.outsider = get_user_model().objects.create_user("stranger", password="pw")
        self.chapter = Chapter.objects.create(trip=self.trip, title="Coast", position=0)
        self.entry = Entry.objects.create(trip=self.trip, author=self.user, occurred_at=WHEN)
        self.track = Track.objects.create(trip=self.trip, gpx_text=make_gpx(5), uploaded_by=self.user)
        self.photo = Media.objects.create(entry=self.entry, kind=Media.PHOTO, sha256="x" * 64,
                                          size_bytes=1, original="originals/x.jpg")

    def test_non_member_gets_not_found_everywhere(self):
        u = self.outsider
        calls = [
            lambda: get_trip(u, self.trip.pk),
            lambda: get_owned(u, Entry, pk=self.entry.pk),
            lambda: get_owned(u, Media, pk=self.photo.pk),
            lambda: trips.update_trip(u, self.trip, title="Mine now"),
            lambda: trips.delete_trip(u, self.trip),
            lambda: trips.regenerate_share_token(u, self.trip),
            lambda: chapters.create_chapter(u, self.trip, "Hills"),
            lambda: chapters.rename_chapter(u, self.chapter, "Hills"),
            lambda: chapters.move_chapter(u, self.chapter, "down"),
            lambda: chapters.delete_chapter(u, self.chapter),
            lambda: chapters.set_current_chapter(u, self.trip, self.chapter),
            lambda: entries.create_entry(u, self.trip, occurred_at=WHEN),
            lambda: entries.update_entry(u, self.entry, body="hi"),
            lambda: entries.delete_entry(u, self.entry),
            lambda: tracks.create_track(u, self.trip, gpx_text=make_gpx(5)),
            lambda: tracks.update_track(u, self.track, name="x"),
            lambda: tracks.delete_track(u, self.track),
            lambda: media.delete_media(u, self.photo),
            lambda: media.move_media(u, self.photo, "up"),
            lambda: media.set_cover(u, self.photo),
            lambda: media.retry_processing(u, self.photo),
            lambda: imports.start_import(u, self.trip),
        ]
        for index, call in enumerate(calls):
            with self.subTest(call=index), self.assertRaises(NotFound):
                call()
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.title, "Sri Lanka")
        self.assertTrue(Entry.objects.filter(pk=self.entry.pk).exists())

    def test_import_batch_is_private_to_its_creator(self):
        batch = imports.start_import(self.user, self.trip)
        self.trip.travellers.add(self.other_user)
        with self.assertRaises(NotFound):
            imports.open_batch(self.other_user, batch.pk)
        self.assertEqual(imports.open_batch(self.user, batch.pk), batch)

    def test_create_trip_adds_creator_and_validates(self):
        trip = trips.create_trip(self.user, title="Japan", start_date=date(2027, 4, 1),
                                 end_date=date(2027, 4, 20), timezone="Asia/Tokyo",
                                 new_companion_names=["Ana", " "])
        self.assertEqual(list(trip.travellers.all()), [self.user])
        self.assertEqual([p.name for p in trip.companions.all()], ["Ana"])
        with self.assertRaises(Invalid) as ctx:
            trips.create_trip(self.user, title="Bad", start_date=date(2027, 4, 2),
                              end_date=date(2027, 4, 1), timezone="Mars/Olympus")
        self.assertIn("timezone", ctx.exception.message_dict)

    def test_cannot_add_strangers_as_travellers(self):
        with self.assertRaises(Invalid):
            trips.update_trip(self.user, self.trip, travellers=[self.user, self.outsider])

    def test_entry_validation(self):
        with self.assertRaises(Invalid):
            entries.create_entry(self.user, self.trip, occurred_at=WHEN, latitude=Decimal("6.9"))
        other = self.make_trip(title="Other")
        foreign = Chapter.objects.create(trip=other, title="Elsewhere", position=0)
        with self.assertRaises(Invalid):
            entries.update_entry(self.user, self.entry, chapter=foreign)

    def test_app_entry_source(self):
        entry = entries.create_entry(self.user, self.trip, occurred_at=WHEN, body="From the phone",
                                     source=Entry.SOURCE_APP)
        self.assertEqual(entry.get_source_display(), "iPhone app")

    def test_chapter_current_and_order(self):
        second = chapters.create_chapter(self.user, self.trip, "Hills", make_current=True)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.current_chapter, second)
        chapters.move_chapter(self.user, second, "up")
        self.assertEqual(list(self.trip.chapters.values_list("title", flat=True)), ["Hills", "Coast"])

    def test_track_rejects_bad_gpx(self):
        with self.assertRaises(Invalid):
            tracks.create_track(self.user, self.trip, gpx_text="not gpx")
        with self.assertRaises(Invalid):
            tracks.create_track(self.user, self.trip, gpx_text=b"\xff\xfe")

    def test_cover_must_be_a_photo(self):
        clip = Media.objects.create(entry=self.entry, kind=Media.AUDIO, sha256="y" * 64,
                                    size_bytes=1, original="originals/y.m4a")
        with self.assertRaises(Invalid):
            media.set_cover(self.user, clip)
        media.set_cover(self.user, self.photo)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.cover, self.photo)
