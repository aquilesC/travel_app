from ..access import ensure_member
from ..models import Entry
from ._util import validated

ENTRY_FIELDS = ("occurred_at", "chapter", "body", "place_name", "latitude", "longitude", "is_public")


def create_entry(actor, trip, *, source=Entry.SOURCE_WEB, **fields):
    ensure_member(actor, trip)
    entry = Entry(trip=trip, author=actor, source=source,
                  **{k: v for k, v in fields.items() if k in ENTRY_FIELDS})
    validated(entry)
    entry.save()
    return entry


def update_entry(actor, entry, **fields):
    """Fields left out are unchanged."""
    ensure_member(actor, entry.trip)
    for key, value in fields.items():
        if key in ENTRY_FIELDS:
            setattr(entry, key, value)
    validated(entry)
    entry.save()
    return entry


def delete_entry(actor, entry):
    """Its media files go too (post_delete signal)."""
    ensure_member(actor, entry.trip)
    entry.delete()
