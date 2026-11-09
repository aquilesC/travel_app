from django.contrib import admin

from .models import Chapter, Entry, InboundMessage, Media, Person, Subscriber, Track, Trip


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ["title", "start_date", "end_date", "timezone", "share_enabled"]
    filter_horizontal = ["companions"]
    raw_id_fields = ["cover", "current_chapter"]


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ["trip", "occurred_at", "author", "source", "is_public"]
    list_filter = ["trip", "source", "is_public"]


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ["pk", "entry", "kind", "status", "is_travel_copy", "size_bytes"]
    list_filter = ["kind", "status", "is_travel_copy"]
    raw_id_fields = ["entry"]


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ["message_sid", "from_number", "status", "received_at", "entry"]
    list_filter = ["status"]
    raw_id_fields = ["entry"]


admin.site.register([Person, Chapter, Track, Subscriber])
