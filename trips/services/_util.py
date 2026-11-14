from django.core.exceptions import ValidationError

from .errors import Invalid


def validated(instance, exclude=None):
    """full_clean() an instance, re-raising as Invalid with per-field messages."""
    try:
        instance.full_clean(exclude=exclude, validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        raise Invalid(exc.message_dict if hasattr(exc, "error_dict") else exc.messages) from None
    return instance
