from django.apps import AppConfig


class TripsConfig(AppConfig):
    name = "trips"

    def ready(self):
        from . import signals  # noqa: F401
