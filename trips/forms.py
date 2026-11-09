from zoneinfo import available_timezones

from django import forms

from .models import Chapter, Entry, Person, Track, Trip

TIMEZONE_CHOICES = [(tz, tz) for tz in sorted(available_timezones()) if "/" in tz or tz == "UTC"]
DATETIME_LOCAL = "%Y-%m-%dT%H:%M"


class TripForm(forms.ModelForm):
    timezone = forms.ChoiceField(choices=TIMEZONE_CHOICES, initial="Europe/Amsterdam")
    new_companions = forms.CharField(
        required=False, label="Add people",
        help_text="Comma-separated names of people not in the list yet.",
    )

    class Meta:
        model = Trip
        fields = ["title", "start_date", "end_date", "timezone", "description",
                  "companions", "share_enabled"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 4}),
            "companions": forms.CheckboxSelectMultiple,
        }

    def save(self, commit=True):
        trip = super().save(commit=commit)
        names = [n.strip() for n in self.cleaned_data.get("new_companions", "").split(",") if n.strip()]
        if names and commit:
            for name in names:
                person, _ = Person.objects.get_or_create(name=name)
                trip.companions.add(person)
        return trip


class ChapterForm(forms.ModelForm):
    class Meta:
        model = Chapter
        fields = ["title"]


class EntryForm(forms.ModelForm):
    occurred_at = forms.DateTimeField(
        label="When", input_formats=[DATETIME_LOCAL],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_LOCAL),
        help_text="In the trip's time zone.",
    )

    class Meta:
        model = Entry
        fields = ["occurred_at", "chapter", "body", "place_name", "latitude", "longitude", "is_public"]
        widgets = {"body": forms.Textarea(attrs={"rows": 10})}

    def __init__(self, *args, trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.trip = trip
        self.fields["chapter"].queryset = trip.chapters.all()


class TrackForm(forms.ModelForm):
    gpx_file = forms.FileField(label="GPX file", required=False)

    class Meta:
        model = Track
        fields = ["name", "mode", "chapter"]

    def __init__(self, *args, trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.trip = trip
        self.fields["chapter"].queryset = trip.chapters.all()
        if not self.instance.pk:
            self.fields["gpx_file"].required = True

    def clean_gpx_file(self):
        from django.conf import settings

        from .gpx import GPXError, parse_gpx

        upload = self.cleaned_data.get("gpx_file")
        if not upload:
            return None
        if upload.size > settings.GPX_MAX_BYTES:
            raise forms.ValidationError("GPX files are limited to 50 MB.")
        raw = upload.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise forms.ValidationError("The file is not UTF-8 text.")
        try:
            parse_gpx(text)
        except GPXError as exc:
            raise forms.ValidationError(f"Not a readable GPX file: {exc}")
        return text


class SubscribeForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"placeholder": "you@example.com"}))
    # Honeypot against bots: humans leave it empty.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class AssignInboundForm(forms.Form):
    trip = forms.ModelChoiceField(queryset=Trip.objects.all())
