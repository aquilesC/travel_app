from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Entry, Media, Tombstone


@receiver(post_delete, sender=Media)
def delete_media_files(sender, instance, **kwargs):
    root = Path(settings.MEDIA_ROOT)
    paths = [instance.original.name, *instance.derivatives.values()]
    for relative in {p for p in paths if p}:
        (root / relative).unlink(missing_ok=True)


@receiver(post_save, sender=Media)
@receiver(post_delete, sender=Media)
def touch_entry(sender, instance, **kwargs):
    """A media change (added, processed, removed) counts as a change of its entry for sync."""
    Entry.objects.filter(pk=instance.entry_id).update(updated_at=timezone.now())


@receiver(post_delete, sender=Entry)
def remember_deleted_entry(sender, instance, **kwargs):
    Tombstone.objects.create(trip_id=instance.trip_id, model="entry", object_id=instance.pk)
