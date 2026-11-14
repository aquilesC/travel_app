"""Tailwind foundation (v4 #29): every form renders through the site form renderer."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts import forms as account_forms
from trips import forms as trip_forms
from trips.models import ImportBatch, Trip


class FormRenderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("aquiles", password="pw")
        self.trip = Trip.objects.create(title="T", start_date="2026-12-21", end_date="2026-12-22",
                                        created_by=self.user)
        self.trip.travellers.add(self.user)

    def forms(self):
        batch = ImportBatch.objects.create(created_by=self.user)
        yield trip_forms.TripForm(user=self.user)
        yield trip_forms.ChapterForm()
        yield trip_forms.EntryForm(trip=self.trip)
        yield trip_forms.TrackForm(trip=self.trip)
        yield trip_forms.SubscribeForm()
        yield trip_forms.AssignInboundForm(user=self.user)
        yield trip_forms.TripFromGPXForm(user=self.user)
        yield trip_forms.ImportForm(batch=batch, cameras=[("Apple iPhone", 3)], user=self.user,
                                    guessed_timezone="Asia/Colombo")
        yield account_forms.PrivacyZoneForm()
        for name in dir(account_forms):
            cls = getattr(account_forms, name)
            if isinstance(cls, type) and name.endswith("Form") and cls.__module__ == account_forms.__name__ \
                    and name not in ("PrivacyZoneForm",):
                try:
                    yield cls()
                except TypeError:
                    continue  # needs arguments; covered by its page tests

    def test_every_form_renders_with_site_templates(self):
        for form in self.forms():
            with self.subTest(form=type(form).__name__):
                html = str(form)
                self.assertIn('class="mb-3"', html)
                if any(w.input_type in ("text", "email", "number", "date") for w in
                       (f.field.widget for f in form) if hasattr(w, "input_type")):
                    self.assertIn("field-input", html)

    def test_errors_render(self):
        form = trip_forms.ChapterForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("text-danger", str(form))
