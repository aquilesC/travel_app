"""Member pages: trips, chapters, entries, tracks. Non-members get 404 everywhere."""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import get_owned, get_trip, member_trips
from .forms import AssignInboundForm, ChapterForm, EntryForm, TrackForm, TripForm
from .models import Chapter, Entry, ImportBatch, InboundMessage, Track, Trip
from .services import chapters as chapter_service
from .services import entries as entry_service
from .services import tracks as track_service
from .services import trips as trip_service
from .services.errors import Invalid
from .templatetags.trips_tags import render_markdown
from .timeline import build_timeline


def form_errors(form, exc):
    """Show a service's Invalid on the form it came from."""
    for field, errors in getattr(exc, "message_dict", {"__all__": exc.messages}).items():
        for error in errors:
            form.add_error(field if field in form.fields else None, error)


def trip_fields(data):
    """TripForm.cleaned_data → keyword arguments for the trip service."""
    fields = {k: data[k] for k in trip_service.TRIP_FIELDS if k in data}
    names = data.get("new_companions", "").split(",")
    return dict(fields, travellers=data["travellers"], companions=data["companions"],
                new_companion_names=names)


def recorded_today(trip):
    """[(name, km)] for travellers whose phone recorded positions today (trip time)."""
    from .services.positions import day_km

    today = timezone.localdate(timezone=trip.tz)
    users = trip.travellers.filter(positions__trip=trip).distinct()
    rows = [(u.get_full_name() or u.username, day_km(trip, u, today)) for u in users]
    return [(name, km) for name, km in rows if km > 0]


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
        try:
            trip = trip_service.create_trip(request.user, **trip_fields(form.cleaned_data))
        except Invalid as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Trip created.")
            return redirect(trip)
    return render(request, "trips/trip_form.html", {"form": form})


def trip_edit(request, pk):
    trip = get_trip(request.user, pk)
    form = TripForm(request.POST or None, instance=trip, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            trip_service.update_trip(request.user, trip, **trip_fields(form.cleaned_data))
        except Invalid as exc:
            form_errors(form, exc)
        else:
            if not trip.travellers.filter(pk=request.user.pk).exists():
                messages.success(request, f"You left “{trip.title}”.")
                return redirect("home")
            messages.success(request, "Trip saved.")
            return redirect(trip)
    return render(request, "trips/trip_form.html", {"form": form, "trip": trip})


def trip_delete(request, pk):
    trip = get_trip(request.user, pk)
    if request.method == "POST":
        trip_service.delete_trip(request.user, trip)
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
        "recorded_today": recorded_today(trip),
        "timeline": build_timeline(trip, public_only=public_only),
        "public_only": public_only,
        "chapter_form": ChapterForm(),
    })


@require_POST
def trip_regenerate_token(request, pk):
    trip = get_trip(request.user, pk)
    trip_service.regenerate_share_token(request.user, trip)
    messages.success(request, "New share link created; the old one no longer works.")
    return redirect("trip_edit", pk=trip.pk)


def trip_map_data(request, pk):
    """Moved to the API (v4 #23). Kept as a redirect for one release."""
    return redirect(reverse("api-v1:trip_map", kwargs={"trip_id": pk}), permanent=True)


# Chapters --------------------------------------------------------------------

@require_POST
def chapter_create(request, pk):
    trip = get_trip(request.user, pk)
    form = ChapterForm(request.POST)
    if form.is_valid():
        chapter_service.create_chapter(request.user, trip, form.cleaned_data["title"])
    else:
        messages.error(request, "A chapter needs a title.")
    return redirect(trip)


def chapter_edit(request, pk):
    chapter = get_owned(request.user, Chapter.objects.select_related("trip"), pk=pk)
    form = ChapterForm(request.POST or None, instance=chapter)
    if request.method == "POST" and form.is_valid():
        chapter_service.rename_chapter(request.user, chapter, form.cleaned_data["title"])
        return redirect(chapter.trip)
    return render(request, "trips/simple_form.html", {
        "form": form, "title": "Edit chapter", "cancel_url": chapter.trip.get_absolute_url(),
    })


def chapter_delete(request, pk):
    chapter = get_owned(request.user, Chapter.objects.select_related("trip"), pk=pk)
    trip = chapter.trip
    if request.method == "POST":
        chapter_service.delete_chapter(request.user, chapter)
        return redirect(trip)
    return render(request, "trips/confirm_delete.html", {
        "object": chapter, "what": "chapter",
        "warning": "Its entries are kept, without a chapter.",
        "cancel_url": trip.get_absolute_url(),
    })


@require_POST
def chapter_move(request, pk, direction):
    chapter = get_owned(request.user, Chapter.objects.select_related("trip"), pk=pk)
    chapter_service.move_chapter(request.user, chapter, direction)
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
            fields = {k: form.cleaned_data[k] for k in form.Meta.fields}
            try:
                if entry is None:
                    entry = entry_service.create_entry(request.user, trip, **fields)
                    messages.success(request, "Entry saved.")
                    return redirect("entry_edit", pk=entry.pk)  # so media can be added
                entry_service.update_entry(request.user, entry, **fields)
            except Invalid as exc:
                form_errors(form, exc)
            else:
                messages.success(request, "Entry saved.")
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
    entry = get_owned(request.user, Entry.objects.select_related("trip"), pk=pk)
    trip = entry.trip
    if request.method == "POST":
        entry_service.delete_entry(request.user, entry)
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
        data = form.cleaned_data
        fields = {k: data[k] for k in ("name", "mode", "chapter")}
        try:
            if track is None:
                track_service.create_track(request.user, trip, gpx_text=data["gpx_file"], **fields)
            else:
                track_service.update_track(request.user, track, gpx_text=data.get("gpx_file"), **fields)
        except Invalid as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Track saved.")
            return redirect(trip)
    return render(request, "trips/track_form.html", {"form": form, "trip": trip, "track": track})


def track_create(request, pk):
    return _track_form_page(request, get_trip(request.user, pk))


def track_edit(request, pk):
    track = get_owned(request.user, Track.objects.select_related("trip"), pk=pk)
    return _track_form_page(request, track.trip, track)


def track_delete(request, pk):
    track = get_owned(request.user, Track.objects.select_related("trip"), pk=pk)
    trip = track.trip
    if request.method == "POST":
        track_service.delete_track(request.user, track)
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
