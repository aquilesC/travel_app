"""Profile pictures: any photo in, a 512×512 WebP out."""

import uuid
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()
SIZE = 512
MAX_BYTES = 20 * 1024 * 1024


class AvatarError(ValueError):
    pass


def save_avatar(profile, uploaded_file):
    if uploaded_file.size > MAX_BYTES:
        raise AvatarError("Pictures are limited to 20 MB.")
    try:
        with Image.open(uploaded_file) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(image, (SIZE, SIZE), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise AvatarError("That file is not a picture we can read.") from exc

    relative = f"avatars/{profile.user_id}/{uuid.uuid4().hex}.webp"
    target = Path(settings.MEDIA_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=85)
    remove_avatar(profile, save=False)
    profile.avatar = relative
    profile.save(update_fields=["avatar"])


def remove_avatar(profile, save=True):
    if profile.avatar:
        (Path(settings.MEDIA_ROOT) / profile.avatar).unlink(missing_ok=True)
        profile.avatar = ""
        if save:
            profile.save(update_fields=["avatar"])
