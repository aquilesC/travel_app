"""Opaque cursors over (timestamp, id) orderings."""

import base64
from datetime import datetime

from ninja.errors import HttpError

MAX_LIMIT = 200


def clamp(limit):
    return max(1, min(limit or 50, MAX_LIMIT))


def encode(when, pk):
    return base64.urlsafe_b64encode(f"{when.isoformat()}|{pk}".encode()).decode().rstrip("=")


def decode(cursor):
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        when, pk = raw.rsplit("|", 1)
        return datetime.fromisoformat(when), int(pk)
    except (ValueError, UnicodeDecodeError):
        raise HttpError(400, "Bad cursor.") from None
