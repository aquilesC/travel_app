from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404


class NotFound(Http404):
    """The object doesn't exist, or the actor may not know it exists."""


class Forbidden(PermissionDenied):
    """The actor can see the object but may not do this to it."""


class Invalid(ValidationError):
    """Bad input. `message_dict` holds per-field errors when there are any."""
