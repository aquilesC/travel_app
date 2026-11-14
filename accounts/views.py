from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import invites as invite_logic
from .avatar import AvatarError, remove_avatar, save_avatar
from .forms import AcceptInviteForm, InviteForm, PrivacyZoneForm, ProfileForm, UserForm
from .models import Invite, PrivacyZone, display_name


def account(request):
    profile = request.user.profile
    user_form = UserForm(request.POST or None, instance=request.user)
    profile_form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and user_form.is_valid() and profile_form.is_valid():
        picture = profile_form.cleaned_data.get("picture")
        try:
            with transaction.atomic():
                user_form.save()
                profile = profile_form.save()
                if picture:
                    save_avatar(profile, picture)
        except AvatarError as exc:
            profile_form.add_error("picture", str(exc))
        else:
            messages.success(request, "Account saved.")
            return redirect("account")
    return render(request, "accounts/account.html", {
        "user_form": user_form, "profile_form": profile_form, "profile": profile,
        "zones": request.user.privacy_zones.all(), "zone_form": PrivacyZoneForm(),
    })


@require_POST
def privacy_zone_add(request):
    form = PrivacyZoneForm(request.POST, instance=PrivacyZone(user=request.user))
    if form.is_valid():
        form.save()
        messages.success(request, f"Privacy zone “{form.instance.label}” added.")
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"Couldn't add the zone: {errors}")
    return redirect(reverse("account") + "#privacy-zones")


@require_POST
def privacy_zone_delete(request, pk):
    get_object_or_404(PrivacyZone, pk=pk, user=request.user).delete()
    messages.success(request, "Privacy zone removed.")
    return redirect(reverse("account") + "#privacy-zones")


@require_POST
def avatar_remove(request):
    remove_avatar(request.user.profile)
    messages.success(request, "Picture removed.")
    return redirect("account")


def _visible_user(request, username):
    user = get_object_or_404(get_user_model().objects.select_related("profile"),
                             username=username, is_active=True)
    if not user.profile.is_public and not request.user.is_authenticated:
        raise Http404
    return user


@login_not_required
@require_GET
def public_profile(request, username):
    from trips.stats import user_stats

    user = _visible_user(request, username)
    stats = user_stats(user)
    return render(request, "accounts/public_profile.html", {
        "person": user, "name": display_name(user), **stats,
    })


@login_not_required
@require_GET
def public_avatar(request, username):
    from trips.media import file_response

    user = _visible_user(request, username)
    if not user.profile.avatar:
        raise Http404
    return file_response(user.profile.avatar)


# Invites ---------------------------------------------------------------------

def invites(request):
    form = InviteForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        email, trip = form.cleaned_data["email"], form.cleaned_data["trip"]
        try:
            kind, obj = invite_logic.invite(request.user, email, trip)
        except invite_logic.InviteError as exc:
            form.add_error(None, str(exc))
        else:
            if kind == "added":
                messages.success(request, f"{display_name(obj)} already has an account and was added to “{trip}”.")
            elif kind == "exists":
                messages.info(request, f"{email} already has an account. Pick a trip to add them to it.")
            else:
                messages.success(request, f"Invite sent to {email}.")
            return redirect("invites")
    sent = Invite.objects.filter(invited_by=request.user).select_related("trip", "accepted_by")[:50]
    return render(request, "accounts/invites.html", {"form": form, "sent": sent})


def _own_invite(request, pk):
    return get_object_or_404(Invite, pk=pk, invited_by=request.user, accepted_at__isnull=True)


@require_POST
def invite_resend(request, pk):
    invite = _own_invite(request, pk)
    invite_logic.resend(invite)
    messages.success(request, f"Invite to {invite.email} sent again (valid 14 more days).")
    return redirect("invites")


@require_POST
def invite_revoke(request, pk):
    invite = _own_invite(request, pk)
    invite.delete()
    messages.success(request, f"Invite to {invite.email} revoked.")
    return redirect("invites")


@login_not_required
def invite_accept(request, token):
    invite = invite_logic.valid_invite(token)
    if invite is None:
        return render(request, "accounts/invite_invalid.html", status=404)
    if request.user.is_authenticated:
        return render(request, "accounts/invite_invalid.html", {"logged_in": True, "invite": invite})
    form = AcceptInviteForm(request.POST or None, email=invite.email)
    if request.method == "POST" and form.is_valid():
        try:
            user = invite_logic.accept(
                invite, first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"], password=form.cleaned_data["password1"],
            )
        except invite_logic.InviteError as exc:
            form.add_error(None, str(exc))
        else:
            login(request, user, backend="allauth.account.auth_backends.AuthenticationBackend")
            messages.success(request, f"Welcome, {user.first_name}!")
            return redirect(invite.trip) if invite.trip_id else redirect("home")
    return render(request, "accounts/invite_accept.html", {
        "form": form, "invite": invite, "inviter": display_name(invite.invited_by), "hide_login": True,
    })
