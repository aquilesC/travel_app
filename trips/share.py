"""Public, anonymous pages: the trip share link and email subscriptions."""

from django.contrib.auth.decorators import login_not_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import SubscribeForm
from .models import Subscriber, Trip
from .timeline import build_timeline


def shared_trip(token):
    trip = Trip.objects.filter(share_token=token, share_enabled=True).first()
    if trip is None:
        raise Http404
    return trip


@login_not_required
@require_GET
def share_trip(request, token):
    trip = shared_trip(token)
    timezone.activate(trip.tz)
    cover = trip.cover if trip.cover_id and trip.cover.entry.is_public else None
    return render(request, "trips/share_trip.html", {
        "trip": trip,
        "cover": cover,
        "timeline": build_timeline(trip, public_only=True),
        "share_token": token,
        "subscribe_form": SubscribeForm(),
    })


@login_not_required
@require_GET
def share_map_data(request, token):
    from .gpx import map_data

    return JsonResponse(map_data(shared_trip(token), public_only=True))


@login_not_required
@require_POST
def subscribe(request, token):
    from .tasks import send_subscription_confirmation

    trip = shared_trip(token)
    form = SubscribeForm(request.POST)
    if not form.is_valid() or form.cleaned_data["website"]:
        return render(request, "trips/subscribe_result.html", {
            "trip": trip, "share_token": token, "ok": False,
            "message": "Please enter a valid email address.",
        }, status=400)
    subscriber, created = Subscriber.objects.get_or_create(trip=trip, email=form.cleaned_data["email"])
    if subscriber.unsubscribed_at:  # coming back: start over with a fresh confirmation
        subscriber.unsubscribed_at = subscriber.confirmed_at = None
        subscriber.save(update_fields=["unsubscribed_at", "confirmed_at"])
    if subscriber.confirmed_at is None:
        send_subscription_confirmation.enqueue(subscriber.pk)
    # Same answer either way, so the form can't be used to probe who subscribed.
    return render(request, "trips/subscribe_result.html", {
        "trip": trip, "share_token": token, "ok": True,
        "message": "Check your inbox: we sent you a link to confirm.",
    })


@login_not_required
@require_GET
def subscription_confirm(request, token):
    subscriber = get_object_or_404(Subscriber.objects.select_related("trip"), token=token)
    if subscriber.unsubscribed_at is None and subscriber.confirmed_at is None:
        subscriber.confirmed_at = timezone.now()
        subscriber.save(update_fields=["confirmed_at"])
    return render(request, "trips/subscribe_result.html", {
        "trip": subscriber.trip, "share_token": subscriber.trip.share_token, "ok": True,
        "message": f"You're subscribed. You'll get one email a day when there's news from "
                   f"“{subscriber.trip.title}”.",
    })


@csrf_exempt  # mail clients post one-click unsubscribes without a CSRF token
@login_not_required
@require_http_methods(["GET", "POST"])
def subscription_unsubscribe(request, token):
    """GET shows a button (mail scanners prefetch links); POST unsubscribes.

    POST without a CSRF token also comes from mail clients (RFC 8058 one-click).
    """
    subscriber = get_object_or_404(Subscriber.objects.select_related("trip"), token=token)
    done = False
    if request.method == "POST":
        if subscriber.unsubscribed_at is None:
            subscriber.unsubscribed_at = timezone.now()
            subscriber.save(update_fields=["unsubscribed_at"])
        done = True
    return render(request, "trips/unsubscribe.html", {"subscriber": subscriber, "done": done})
