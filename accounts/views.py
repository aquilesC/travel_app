from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .avatar import AvatarError, remove_avatar, save_avatar
from .forms import ProfileForm, UserForm
from .models import display_name


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
    })


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
