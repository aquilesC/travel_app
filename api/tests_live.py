"""Live location and privacy (v4 #27)."""

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from accounts.models import PrivacyZone
from api.tests_positions import PositionTestCase, batch
from trips.models import Trip
from trips.services.live import snap


class LiveTests(PositionTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.now = timezone.now().replace(microsecond=0)
        today = timezone.localdate(timezone=self.trip.tz)
        self.trip.start_date, self.trip.end_date = today - timedelta(days=1), today + timedelta(days=1)
        self.trip.save()
        # one point per minute for the last 3 hours
        self.post(batch(180, start=self.now - timedelta(minutes=179), step=timedelta(minutes=1),
                        lat=6.90, lon=79.85))

    def share_live(self):
        return Client().get(f"/api/v1/share/{self.trip.share_token}/live")

    def test_members_only_hides_share_live(self):
        self.assertEqual(self.trip.live_share, Trip.LIVE_MEMBERS)
        self.assertEqual(self.share_live().status_code, 404)

    def test_link_viewers_get_delayed_rounded_points(self):
        self.trip.live_share = Trip.LIVE_LINK
        self.trip.save()
        response = self.share_live()
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        latest = body["travellers"][0]["latest"]
        recorded = timezone.datetime.fromisoformat(latest["recorded_at"])
        self.assertLessEqual(recorded, self.now - timedelta(minutes=59))
        self.assertEqual((latest["latitude"], latest["longitude"]),
                         snap(latest["latitude"], latest["longitude"], 1000))
        exact_latest = 6.90 + 179 * 0.0005
        self.assertNotEqual(latest["latitude"], round(exact_latest, 6))
        self.assertEqual(body["delay_minutes"], 60)

    def test_members_see_exact_latest_immediately(self):
        body = self.api("get", f"/trips/{self.trip.pk}/live", token=self.token_value).json()
        latest = body["travellers"][0]["latest"]
        self.assertAlmostEqual(latest["latitude"], 6.90 + 179 * 0.0005, places=6)
        self.assertEqual(timezone.datetime.fromisoformat(latest["recorded_at"]), self.now)

    def test_privacy_zone_hides_points_everywhere(self):
        last_lat = 6.90 + 179 * 0.0005
        PrivacyZone.objects.create(user=self.user, label="Hotel", latitude=Decimal(f"{last_lat:.6f}"),
                                   longitude=Decimal("79.85"), radius_m=300)
        self.trip.live_share = Trip.LIVE_LINK
        self.trip.live_delay_minutes = 0
        self.trip.live_round_m = 0
        self.trip.save()
        cache.clear()
        member = self.api("get", f"/trips/{self.trip.pk}/live", token=self.token_value).json()
        latest = member["travellers"][0]["latest"]
        self.assertLess(latest["latitude"], last_lat - 0.0025)  # ≥ ~300 m before the zone
        for lon, lat in member["travellers"][0]["path"]:
            self.assertLess(lat, last_lat - 0.0025)
        shared = self.share_live().json()
        self.assertLess(shared["travellers"][0]["latest"]["latitude"], last_lat - 0.0025)
        self.client.force_login(self.user)
        feature = next(f for f in self.client.get(f"/api/v1/trips/{self.trip.pk}/map").json()["features"]
                       if f["properties"]["kind"] == "recorded")
        for line in feature["geometry"]["coordinates"]:
            for lon, lat in line:
                self.assertLess(lat, last_lat - 0.0025)

    def test_off_hides_from_members_too(self):
        self.trip.live_share = Trip.LIVE_OFF
        self.trip.save()
        body = self.api("get", f"/trips/{self.trip.pk}/live", token=self.token_value).json()
        self.assertEqual(body["travellers"], [])

    def test_stale_positions_are_not_shown(self):
        from django.db.models import F

        self.trip.positions.update(recorded_at=F("recorded_at") - timedelta(days=2))
        body = self.api("get", f"/trips/{self.trip.pk}/live", token=self.token_value).json()
        self.assertEqual(body["travellers"], [])

    def test_pages_include_live_url_by_setting(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(f"/trips/{self.trip.pk}/"), "data-live-url")
        share = Client().get(f"/s/{self.trip.share_token}/")
        self.assertNotContains(share, "data-live-url")
        self.trip.live_share = Trip.LIVE_LINK
        self.trip.save()
        self.assertContains(Client().get(f"/s/{self.trip.share_token}/"), "data-live-url")

    def test_account_page_manages_zones(self):
        self.client.force_login(self.user)
        response = self.client.post("/account/privacy-zones/", {
            "label": "Home", "latitude": "52.37", "longitude": "4.89", "radius_m": "100"})
        self.assertFalse(PrivacyZone.objects.exists())  # below the 200 m minimum
        self.client.post("/account/privacy-zones/", {
            "label": "Home", "latitude": "52.37", "longitude": "4.89", "radius_m": "400"})
        zone = PrivacyZone.objects.get()
        me = self.api("get", "/me", token=self.token_value).json()
        self.assertEqual(me["privacy_zones"][0]["radius_m"], 400)
        self.client.post(f"/account/privacy-zones/{zone.pk}/delete/")
        self.assertFalse(PrivacyZone.objects.exists())
