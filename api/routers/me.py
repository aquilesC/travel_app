from django.urls import reverse
from ninja import Router, Schema

router = Router(tags=["me"])


class PrivacyZoneOut(Schema):
    id: int
    label: str
    latitude: float
    longitude: float
    radius_m: int


class MeOut(Schema):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    name: str
    avatar_url: str | None
    privacy_zones: list[PrivacyZoneOut]


class MeIn(Schema):
    first_name: str | None = None
    last_name: str | None = None


def _me(user):
    profile = getattr(user, "profile", None)
    avatar = reverse("public_avatar", args=[user.username]) if profile and profile.avatar else None
    return {"id": user.pk, "username": user.username, "email": user.email,
            "first_name": user.first_name, "last_name": user.last_name,
            "name": user.get_full_name() or user.username, "avatar_url": avatar,
            "privacy_zones": [{"id": z.pk, "label": z.label, "latitude": float(z.latitude),
                               "longitude": float(z.longitude), "radius_m": z.radius_m}
                              for z in user.privacy_zones.all()]}


@router.get("", response=MeOut)
def me(request):
    """The logged-in user."""
    return _me(request.user)


@router.patch("", response=MeOut)
def update_me(request, payload: MeIn):
    user = request.user
    for field, value in payload.dict(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value.strip()[:150])
    user.save(update_fields=["first_name", "last_name"])
    return _me(user)
