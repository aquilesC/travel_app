"""Member pages: trips, chapters, entries, tracks. Non-members get 404 everywhere."""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import get_owned, get_trip, member_trips
from .forms import AssignInboundForm, ChapterForm, EntryForm, TrackForm, TripForm
from .models import Chapter, Entry, ImportBatch, InboundMessage, Track, Trip, new_token
from .templatetags.trips_tags import render_markdown
from .timeline import build_timeline


def own_unrouted(user):
    number = getattr(getattr(user, "profile", None), "whatsapp_number", None)
    if not number:
        return InboundMessage.objects.none()
    return InboundMessage.objects.filter(status=InboundMessage.UNROUTED, from_number=number)


@login_not_required
def home(request):
    if not request.user.is_authenticated:
        return render(request, "landing.html", {"hide_login": False})
    return render(request, "trips/home.html", {
        "trips": member_trips(request.user).select_related("cover").prefetch_related("companions", "travellers"),
        "unrouted": own_unrouted(request.user),
        "assign_form": AssignInboundForm(user=request.user),
        "open_imports": ImportBatch.objects.filter(status=ImportBatch.OPEN, created_by=request.user,
                                                   items__isnull=False).select_related("trip").distinct(),
    })


# Trips -----------------------------------------------------------------------

def trip_create(request):
    form = TripForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.instance.created_by = request.user
        trip = form.save()
        trip.travellers.add(request.user)  # creator is always a member
        messages.success(request, "Trip created.")
        return redirect(trip)
    return render(request, "trips/trip_form.html", {"form": form})


def trip_edit(request, pk):
    trip = get_trip(request.user, pk)
    form = TripForm(request.POST or None, instance=trip, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        if not trip.travellers.filter(pk=request.user.pk).exists():
            messages.success(request, f"You left “{trip.title}”.")
            return redirect("home")
        messages.success(request, "Trip saved.")
        return redirect(trip)
    return render(request, "trips/trip_form.html", {"form": form, "trip": trip})


def trip_delete(request, pk):
    trip = get_trip(request.user, pk)
    if request.method == "POST":
        trip.delete()
        messages.success(request, f"Deleted “{trip.title}”.")
        return redirect("home")
    return render(request, "trips/confirm_delete.html", {
        "object": trip, "what": "trip",
        "warning": "All its entries, photos, videos and tracks are deleted too, for every member.",
        "cancel_url": trip.get_absolute_url(),
    })


def trip_detail(request, pk):
    trip = get_trip(request.user, pk, Trip.objects.prefetch_related("companions", "tracks", "travellers"))
    timezone.activate(trip.tz)
    public_only = request.GET.get("public") == "1"
    return render(request, "trips/trip_detail.html", {
        "trip": trip,
        "timeline": build_timeline(trip, public_only=public_only),
        "public_only": public_only,
        "chapter_form": ChapterForm(),
    })


@require_POST
def trip_regenerate_token(request, pk):
    trip = get_trip(request.user, pk)
    trip.share_token = new_token()
    trip.save(update_fields=["share_token", "updated_at"])
    messages.success(request, "New share link created; the old one no longer works.")
    return redirect("trip_edit", pk=trip.pk)


def trip_map_data(request, pk):
    from .gpx import map_data

    trip = get_trip(request.user, pk)
    return JsonResponse(map_data(
        trip, public_only=False, media_url=lambda m, v: reverse("serve_media", args=[m.pk, v])))


# Chapters --------------------------------------------------------------------

@require_POST
def chapter_create(request, pk):
    trip = get_trip(request.user, pk)
    form = ChapterForm(request.POST)
    if form.is_valid():
        form.instance.trip = trip
        form.instance.position = Chapter.next_position(trip)
        form.save()
    else:
        messages.error(request, "A chapter needs a title.")
    return redirect(trip)


def chapter_edit(request, pk):
    chapter = get_owned(request.user, Chapter, pk=pk)
    form = ChapterForm(request.POST or None, instance=chapter)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(chapter.trip)
    return render(request, "trips/simple_form.html", {
        "form": form, "title": "Edit chapter", "cancel_url": chapter.trip.get_absolute_url(),
    })


def chapter_delete(request, pk):
    chapter = get_owned(request.user, Chapter, pk=pk)
    trip = chapter.trip
    if request.method == "POST":
        chapter.delete()
        return redirect(trip)
    return render(request, "trips/confirm_delete.html", {
        "object": chapter, "what": "chapter",
        "warning": "Its entries are kept, without a chapter.",
        "cancel_url": trip.get_absolute_url(),
    })


@require_POST
def chapter_move(request, pk, direction):
    chapter = get_owned(request.user, Chapter, pk=pk)
    siblings = chapter.trip.chapters.all()
    if direction == "up":
        other = siblings.filter(position__lt=chapter.position).order_by("-position").first()
    else:
        other = siblings.filter(position__gt=chapter.position).order_by("position").first()
    if other:
        with transaction.atomic():
            a, b = chapter.position, other.position
            # Park one row outside the range so the unique constraint holds.
            Chapter.objects.filter(pk=chapter.pk).update(position=10**6)
            Chapter.objects.filter(pk=other.pk).update(position=a)
            Chapter.objects.filter(pk=chapter.pk).update(position=b)
    return redirect(chapter.trip)


# Entries ---------------------------------------------------------------------

def _entry_form_page(request, trip, entry=None):
    timezone.activate(trip.tz)  # form times are read and shown in the trip's zone
    initial = {}
    if entry is None:
        initial = {"occurred_at": timezone.localtime().replace(second=0, microsecond=0)}
        if request.GET.get("chapter"):
            initial["chapter"] = request.GET["chapter"]
    form = EntryForm(request.POST or None, instance=entry, trip=trip, initial=initial)
    preview = None
    if request.method == "POST" and form.is_valid():
        if "preview" in request.POST:
            preview = render_markdown(form.cleaned_data["body"])
        else:
            is_new = form.instance.pk is None
            if is_new:
                form.instance.author = request.user
            entry = form.save()
            messages.success(request, "Entry saved.")
            if is_new:
                return redirect("entry_edit", pk=entry.pk)  # so media can be added
            return redirect(entry)
    return render(request, "trips/entry_form.html", {
        "form": form, "trip": trip, "entry": entry, "preview": preview,
    })


def entry_create(request, pk):
    return _entry_form_page(request, get_trip(request.user, pk))


def entry_edit(request, pk):
    entry = get_owned(request.user, Entry.objects.select_related("trip"), pk=pk)
    return _entry_form_page(request, entry.trip, entry)


def entry_delete(request, pk):
    entry = get_owned(request.user, Entry, pk=pk)
    trip = entry.trip
    if request.method == "POST":
        entry.delete()
        messages.success(request, "Entry deleted.")
        return redirect(trip)
    return render(request, "trips/confirm_delete.html", {
        "object": entry, "what": "entry",
        "warning": "Its photos, videos and audio are deleted too.",
        "cancel_url": entry.get_absolute_url(),
    })


# Tracks ----------------------------------------------------------------------

def _track_form_page(request, trip, track=None):
    form = TrackForm(request.POST or None, request.FILES or None, instance=track, trip=trip)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("gpx_file"):
            form.instance.gpx_text = form.cleaned_data["gpx_file"]
        if form.instance.pk is None:
            form.instance.uploaded_by = request.user
        form.save()
        messages.success(request, "Track saved.")
        return redirect(trip)
    return render(request, "trips/track_form.html", {"form": form, "trip": trip, "track": track})


def track_create(request, pk):
    return _track_form_page(request, get_trip(request.user, pk))


def track_edit(request, pk):
    track = get_owned(request.user, Track, pk=pk)
    return _track_form_page(request, track.trip, track)


def track_delete(request, pk):
    track = get_owned(request.user, Track, pk=pk)
    trip = track.trip
    if request.method == "POST":
        track.delete()
        return redirect(trip)
    return render(request, "trips/confirm_delete.html", {
        "object": track, "what": "track", "warning": "The GPX file is deleted.",
        "cancel_url": trip.get_absolute_url(),
    })


# WhatsApp messages that arrived outside any trip -------------------------------

@require_POST
def inbound_assign(request, pk):
    from .tasks import process_inbound

    message = get_object_or_404(own_unrouted(request.user), pk=pk)
    form = AssignInboundForm(request.POST, user=request.user)
    if form.is_valid():
        process_inbound.enqueue(message.pk, trip_id=form.cleaned_data["trip"].pk)
        messages.success(request, f"Message queued for “{form.cleaned_data['trip']}”.")
    return redirect("home")
