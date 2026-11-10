"""Views for bulk photo imports (#11, #13) and trips from GPX (#12)."""

from collections import Counter
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import importing
from .forms import ImportForm, TripFromGPXForm
from .models import ImportBatch, Trip


@require_POST
def trip_import_start(request, pk):
    trip = get_object_or_404(Trip, pk=pk)
    batch = ImportBatch.objects.create(trip=trip, created_by=request.user)
    return redirect("import_upload", batch_id=batch.pk)


@require_POST
def import_new(request):
    batch = ImportBatch.objects.create(created_by=request.user)
    return redirect("import_upload", batch_id=batch.pk)


def _open_batch(batch_id):
    return get_object_or_404(ImportBatch.objects.select_related("trip"), pk=batch_id,
                             status=ImportBatch.OPEN)


def import_upload(request, batch_id):
    batch = _open_batch(batch_id)
    return render(request, "trips/import_upload.html", {"batch": batch, "count": batch.items.count()})


def _summary(batch, items, tz, shifts):
    series = importing.track_series(batch.trip.tracks.all()) if batch.trip_id else []
    dated, undated = importing.build_points(items, tz, shifts, series)
    groups = importing.group_points(dated) + ([undated] if undated else [])
    start, end = importing.date_range(items, tz, shifts)
    sources = Counter(p.source or "none" for p in dated + undated)
    return {
        "files": len(items), "undated": len(undated), "entries": len(groups),
        "start": start, "end": end,
        "from_file": sources["exif"], "from_gpx": sources["gpx"],
        "estimated": sources["interpolated"], "no_location": sources["none"],
    }


def import_review(request, batch_id):
    batch = _open_batch(batch_id)
    items = list(batch.items.all())
    if not items:
        messages.error(request, "Upload some photos first.")
        return redirect("import_upload", batch_id=batch.pk)
    cameras = sorted(Counter(i.camera for i in items).items(), key=lambda c: -c[1])
    guessed = importing.guess_timezone(items)
    form = ImportForm(request.POST or None, request.FILES or None, batch=batch, cameras=cameras,
                      guessed_timezone=guessed)

    tz_name = batch.trip.timezone if batch.trip_id else guessed
    shifts = {}
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        shifts = data["shifts"]
        tz_name = data.get("timezone") or tz_name
        if "create" in request.POST:
            if batch.trip_id:
                entries = importing.create_entries(batch, batch.trip, shifts, data["make_public"],
                                                   request.user)
                trip = batch.trip
            else:
                trip = importing.create_trip_from_batch(
                    batch, title=data["title"], tz_name=tz_name, travellers=data["travellers"],
                    gpx_texts=[(importing.gpx_name(text, name), text) for name, text in data["gpx_files"]],
                    shifts=shifts, make_public=data["make_public"], author=request.user,
                )
                entries = trip.entries.all()
            messages.success(request, f"Added {len(items)} files in {len(entries)} entries. "
                                      "Photos and videos are being processed.")
            return redirect(trip)

    return render(request, "trips/import_review.html", {
        "batch": batch, "form": form, "timezone": tz_name,
        "summary": _summary(batch, items, ZoneInfo(tz_name), shifts),
    })


@require_POST
def import_discard(request, batch_id):
    batch = _open_batch(batch_id)
    trip = batch.trip
    importing.discard_batch(batch)
    messages.success(request, "Import discarded.")
    return redirect(trip) if trip else redirect("home")


def trip_from_gpx(request):
    form = TripFromGPXForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        trip = importing.create_trip_from_gpx(
            files=data["gpx_files"], tz_name=data["timezone"], mode=data["mode"], title=data["title"],
            start_date=data["start_date"], end_date=data["end_date"], travellers=data["travellers"],
            author=request.user,
        )
        messages.success(request, f"Trip created with {trip.tracks.count()} track(s).")
        return redirect(trip)
    return render(request, "trips/trip_from_gpx.html", {"form": form})
