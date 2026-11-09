from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Media


@receiver(post_delete, sender=Media)
def delete_media_files(sender, instance, **kwargs):
    root = Path(settings.MEDIA_ROOT)
    paths = [instance.original.name, *instance.derivatives.values()]
    for relative in {p for p in paths if p}:
        (root / relative).unlink(missing_ok=True)
