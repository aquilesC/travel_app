from dataclasses import dataclass

from django.db.models import Prefetch

from .models import Media


@dataclass
class Section:
    chapter: object  # Chapter or None (entries before any chapter)
    entries: list
    next_chapter: object = None


def build_timeline(trip, public_only=False):
    """[Section, ...] in chapter order, entries by time.

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

    sections = []
    if groups[None]:
        sections.append(Section(None, groups[None]))
    for chapter in chapters:
        if groups[chapter.pk] or not public_only:
            sections.append(Section(chapter, groups[chapter.pk]))
    named = [s for s in sections if s.chapter]
    for current, following in zip(named, named[1:]):
        current.next_chapter = following.chapter
    return sections
