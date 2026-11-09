from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        from django.conf import settings
        from django.db.models.signals import post_save

        from .models import create_profile

        post_save.connect(create_profile, sender=settings.AUTH_USER_MODEL)
