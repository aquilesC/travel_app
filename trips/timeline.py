from django.db.models import Prefetch

from .models import Media


def build_timeline(trip, public_only=False):
    """[(chapter_or_None, [entries...]), ...] in chapter order, entries by time.

    Entries without a chapter come first (e.g. WhatsApp posts before any #chapter).
    """
    entries = trip.entries.select_related("author", "chapter").prefetch_related(
        Prefetch("media", queryset=Media.objects.order_by("position", "id"))
    )
    if public_only:
        entries = entries.filter(is_public=True)

    groups = {None: []}
    chapters = list(trip.chapters.all())
    for chapter in chapters:
        groups[chapter.pk] = []
    for entry in entries:
        groups.setdefault(entry.chapter_id, []).append(entry)

    timeline = []
    if groups[None]:
        timeline.append((None, groups[None]))
    for chapter in chapters:
        if groups[chapter.pk] or not public_only:
            timeline.append((chapter, groups[chapter.pk]))
    return timeline
