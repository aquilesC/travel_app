from django import forms
from django.contrib.auth import get_user_model

from .models import Profile


class UserForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email"]


class ProfileForm(forms.ModelForm):
    picture = forms.FileField(
        required=False, label="Profile picture",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*,.heic,.heif"}),
    )

    class Meta:
        model = Profile
        fields = ["whatsapp_number", "is_public"]
