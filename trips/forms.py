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
                  "travellers", "companions", "share_enabled"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 4}),
            "travellers": forms.CheckboxSelectMultiple,
            "companions": forms.CheckboxSelectMultiple,
        }
        labels = {"travellers": "Who of us went", "companions": "Travelling with"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model

        self.fields["travellers"].queryset = get_user_model().objects.filter(is_active=True)
        self.fields["travellers"].label_from_instance = lambda u: u.get_full_name() or u.username
        if not self.instance.pk:
            self.initial.setdefault("travellers", list(self.fields["travellers"].queryset))

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


# Imports (#11-#13) ---------------------------------------------------------------

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleGPXField(forms.FileField):
    """Several GPX files → [(filename, text)], each validated and size-capped."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": ".gpx,application/gpx+xml"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        from django.conf import settings

        from .gpx import GPXError, parse_gpx

        files = [f for f in (data if isinstance(data, (list, tuple)) else [data]) if f]
        if not files:
            if self.required:
                raise forms.ValidationError("Choose at least one GPX file.")
            return []
        result, errors = [], []
        for upload in files:
            if upload.size > settings.GPX_MAX_BYTES:
                errors.append(f"{upload.name}: larger than 50 MB.")
                continue
            try:
                text = upload.read().decode("utf-8-sig")
                parse_gpx(text)
            except UnicodeDecodeError:
                errors.append(f"{upload.name}: not UTF-8 text.")
                continue
            except GPXError as exc:
                errors.append(f"{upload.name}: not a readable GPX file ({exc}).")
                continue
            result.append((upload.name, text))
        if errors:
            raise forms.ValidationError(errors)
        return result


def _traveller_field():
    from django.contrib.auth import get_user_model

    users = get_user_model().objects.filter(is_active=True)
    field = forms.ModelMultipleChoiceField(
        queryset=users, required=False, widget=forms.CheckboxSelectMultiple,
        initial=list(users), label="Who of us went",
    )
    field.label_from_instance = lambda u: u.get_full_name() or u.username
    return field


class TripFromGPXForm(forms.Form):
    gpx_files = MultipleGPXField(label="GPX files")
    mode = forms.ChoiceField(choices=Track.MODES, initial="hike", label="Travel mode")
    timezone = forms.ChoiceField(choices=TIMEZONE_CHOICES, initial="Europe/Amsterdam",
                                 help_text="Trip dates and times are shown in this zone.")
    title = forms.CharField(required=False, max_length=200,
                            help_text="Leave empty to use the track's name.")
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}),
                                 help_text="Only needed when the GPX files have no timestamps.")
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["travellers"] = _traveller_field()

    def clean(self):
        from .importing import has_timestamps

        data = super().clean()
        files = data.get("gpx_files") or []
        if files and not any(has_timestamps(text) for _, text in files):
            if not (data.get("start_date") and data.get("end_date")):
                raise forms.ValidationError(
                    "These GPX files have no timestamps, so enter the start and end dates.")
            if data["end_date"] < data["start_date"]:
                raise forms.ValidationError("The trip can't end before it starts.")
        return data


class ImportForm(forms.Form):
    """Review step of a bulk import. Adds trip fields when the import creates a trip."""

    make_public = forms.BooleanField(required=False, initial=True,
                                     label="Show the new entries on the share link")

    def __init__(self, *args, batch, cameras, guessed_timezone=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cameras = cameras
        for index, (camera, _count) in enumerate(cameras):
            self.fields[f"shift_{index}"] = forms.CharField(
                required=False, initial="+0:00", label=camera or "Unknown camera",
                help_text="Shift this camera's clock, e.g. -1:00 or +5:30.",
            )
        if batch.trip_id is None:
            self.fields["title"] = forms.CharField(required=False, max_length=200)
            self.fields["timezone"] = forms.ChoiceField(choices=TIMEZONE_CHOICES,
                                                        initial=guessed_timezone)
            self.fields["travellers"] = _traveller_field()
            self.fields["gpx_files"] = MultipleGPXField(
                required=False, label="GPX tracks (optional)",
                help_text="Used to place photos without a location, and shown on the map.")

    def clean(self):
        from .importing import parse_shift

        data = super().clean()
        shifts = {}
        for index, (camera, _count) in enumerate(self.cameras):
            try:
                shifts[camera] = parse_shift(data.get(f"shift_{index}"))
            except ValueError:
                self.add_error(f"shift_{index}", "Use hours:minutes, e.g. -1:00 or +5:30.")
        data["shifts"] = shifts
        return data

    def shift_fields(self):
        return [self[f"shift_{i}"] for i in range(len(self.cameras))]
