"""Owner-side pages: trips, chapters, entries, tracks. All require login."""

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import AssignInboundForm, ChapterForm, EntryForm, TrackForm, TripForm
from .models import Chapter, Entry, ImportBatch, InboundMessage, Track, Trip, new_token
from .templatetags.trips_tags import render_markdown
from .timeline import build_timeline


def home(request):
    return render(request, "trips/home.html", {
        "trips": Trip.objects.select_related("cover").prefetch_related("companions"),
        "unrouted": InboundMessage.objects.filter(status=InboundMessage.UNROUTED),
        "assign_form": AssignInboundForm(),
        "open_imports": ImportBatch.objects.filter(status=ImportBatch.OPEN, items__isnull=False)
                                           .select_related("trip").distinct(),
    })


# Trips -----------------------------------------------------------------------

def trip_create(request):
    form = TripForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.instance.created_by = request.user
        trip = form.save()
        messages.success(request, "Trip created.")
        return redirect(trip)
    return render(request, "trips/trip_form.html", {"form": form})


def trip_edit(request, pk):
    trip = get_object_or_404(Trip, pk=pk)
    form = TripForm(request.POST or None, instance=trip)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Trip saved.")
        return redirect(trip)
    return render(request, "trips/trip_form.html", {"form": form, "trip": trip})


def trip_delete(request, pk):
    trip = get_object_or_404(Trip, pk=pk)
    if request.method == "POST":
        trip.delete()
        messages.success(request, f"Deleted “{trip.title}”.")
        return redirect("home")
    return render(request, "trips/confirm_delete.html", {
        "object": trip, "what": "trip",
        "warning": "All its entries, photos, videos and tracks are deleted too.",
        "cancel_url": trip.get_absolute_url(),
    })


def trip_detail(request, pk):
    trip = get_object_or_404(Trip.objects.prefetch_related("companions", "tracks"), pk=pk)
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
    trip = get_object_or_404(Trip, pk=pk)
    trip.share_token = new_token()
    trip.save(update_fields=["share_token", "updated_at"])
    messages.success(request, "New share link created; the old one no longer works.")
    return redirect("trip_edit", pk=trip.pk)


def trip_map_data(request, pk):
    from .gpx import map_data

    trip = get_object_or_404(Trip, pk=pk)
    return JsonResponse(map_data(trip, public_only=False))


# Chapters --------------------------------------------------------------------

@require_POST
def chapter_create(request, pk):
    trip = get_object_or_404(Trip, pk=pk)
    form = ChapterForm(request.POST)
    if form.is_valid():
        form.instance.trip = trip
        form.instance.position = Chapter.next_position(trip)
        form.save()
    else:
        messages.error(request, "A chapter needs a title.")
    return redirect(trip)


def chapter_edit(request, pk):
    chapter = get_object_or_404(Chapter, pk=pk)
    form = ChapterForm(request.POST or None, instance=chapter)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(chapter.trip)
    return render(request, "trips/simple_form.html", {
        "form": form, "title": "Edit chapter", "cancel_url": chapter.trip.get_absolute_url(),
    })


def chapter_delete(request, pk):
    chapter = get_object_or_404(Chapter, pk=pk)
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
    chapter = get_object_or_404(Chapter, pk=pk)
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
    return _entry_form_page(request, get_object_or_404(Trip, pk=pk))


def entry_edit(request, pk):
    entry = get_object_or_404(Entry.objects.select_related("trip"), pk=pk)
    return _entry_form_page(request, entry.trip, entry)


def entry_delete(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
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
    return _track_form_page(request, get_object_or_404(Trip, pk=pk))


def track_edit(request, pk):
    track = get_object_or_404(Track, pk=pk)
    return _track_form_page(request, track.trip, track)


def track_delete(request, pk):
    track = get_object_or_404(Track, pk=pk)
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

    message = get_object_or_404(InboundMessage, pk=pk, status=InboundMessage.UNROUTED)
    form = AssignInboundForm(request.POST)
    if form.is_valid():
        process_inbound.enqueue(message.pk, trip_id=form.cleaned_data["trip"].pk)
        messages.success(request, f"Message queued for “{form.cleaned_data['trip']}”.")
    return redirect("home")
