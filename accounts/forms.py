import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import Profile, PrivacyZone


class UserForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "username"]
        help_texts = {"username": "Your public profile lives at /u/<username>/. Letters, digits and . _ - only."}

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,40}", username):
            raise forms.ValidationError("Use 2–40 letters, digits, dots, dashes or underscores.")
        return username


class ProfileForm(forms.ModelForm):
    picture = forms.FileField(
        required=False, label="Profile picture",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*,.heic,.heif"}),
    )

    class Meta:
        model = Profile
        fields = ["whatsapp_number", "is_public"]


class InviteForm(forms.Form):
    email = forms.EmailField()
    trip = forms.ModelChoiceField(queryset=None, required=False, empty_label="No trip, just the app",
                                  help_text="They join this trip as a member when they accept.")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["trip"].queryset = user.travelled_trips.all()

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class AcceptInviteForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    password1 = forms.CharField(label="Choose a password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repeat the password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, email, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords don't match.")
        elif p1:
            user = get_user_model()(email=self.email, first_name=data.get("first_name", ""),
                                    last_name=data.get("last_name", ""))
            try:
                validate_password(p1, user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class PrivacyZoneForm(forms.ModelForm):
    class Meta:
        model = PrivacyZone
        fields = ["label", "latitude", "longitude", "radius_m"]
        labels = {"radius_m": "Radius (metres)"}
        widgets = {"latitude": forms.NumberInput(attrs={"step": "0.000001"}),
                   "longitude": forms.NumberInput(attrs={"step": "0.000001"})}
