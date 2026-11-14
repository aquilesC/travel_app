from django.db import transaction

from ..access import ensure_member
from ..models import Chapter
from ._util import validated


def create_chapter(actor, trip, title, *, make_current=False):
    ensure_member(actor, trip)
    chapter = Chapter(trip=trip, title=(title or "").strip()[:200], position=Chapter.next_position(trip))
    validated(chapter)
    chapter.save()
    if make_current:
        set_current_chapter(actor, trip, chapter)
    return chapter


def rename_chapter(actor, chapter, title):
    ensure_member(actor, chapter.trip)
    chapter.title = (title or "").strip()[:200]
    validated(chapter)
    chapter.save(update_fields=["title"])
    return chapter


def delete_chapter(actor, chapter):
    """Entries and tracks are kept, without a chapter."""
    ensure_member(actor, chapter.trip)
    chapter.delete()


def move_chapter(actor, chapter, direction):
    ensure_member(actor, chapter.trip)
    siblings = chapter.trip.chapters.all()
    if direction == "up":
        other = siblings.filter(position__lt=chapter.position).order_by("-position").first()
    else:
        other = siblings.filter(position__gt=chapter.position).order_by("position").first()
    if other:
        with transaction.atomic():
            a, b = chapter.position, other.position
            # Park one row outside the range so the unique constraint holds.
            Chapter.objects.filter(pk=chapter.pk).update(position=10**6)
            Chapter.objects.filter(pk=other.pk).update(position=a)
            Chapter.objects.filter(pk=chapter.pk).update(position=b)
        chapter.position = b
    return chapter


def set_current_chapter(actor, trip, chapter):
    """The chapter new posts (WhatsApp, app) go into. None clears it."""
    ensure_member(actor, trip)
    if chapter is not None and chapter.trip_id != trip.pk:
        from .errors import Invalid

        raise Invalid({"chapter": ["That chapter belongs to another trip."]})
    trip.current_chapter = chapter
    trip.save(update_fields=["current_chapter", "updated_at"])
    return trip
