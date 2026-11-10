from django.urls import path

from . import imports, media, share, views, whatsapp

urlpatterns = [
    path("", views.home, name="home"),
    # Imports
    path("trips/from-gpx/", imports.trip_from_gpx, name="trip_from_gpx"),
    path("trips/<int:pk>/import/", imports.trip_import_start, name="trip_import_start"),
    path("imports/new/", imports.import_new, name="import_new"),
    path("imports/<uuid:batch_id>/", imports.import_upload, name="import_upload"),
    path("imports/<uuid:batch_id>/uploads/", media.batch_upload_start, name="batch_upload_start"),
    path("imports/<uuid:batch_id>/review/", imports.import_review, name="import_review"),
    path("imports/<uuid:batch_id>/discard/", imports.import_discard, name="import_discard"),
    # Trips
    path("trips/new/", views.trip_create, name="trip_create"),
    path("trips/<int:pk>/", views.trip_detail, name="trip_detail"),
    path("trips/<int:pk>/edit/", views.trip_edit, name="trip_edit"),
    path("trips/<int:pk>/delete/", views.trip_delete, name="trip_delete"),
    path("trips/<int:pk>/share/regenerate/", views.trip_regenerate_token, name="trip_regenerate_token"),
    path("trips/<int:pk>/map.json", views.trip_map_data, name="trip_map_data"),
    # Chapters
    path("trips/<int:pk>/chapters/new/", views.chapter_create, name="chapter_create"),
    path("chapters/<int:pk>/edit/", views.chapter_edit, name="chapter_edit"),
    path("chapters/<int:pk>/delete/", views.chapter_delete, name="chapter_delete"),
    path("chapters/<int:pk>/move/<str:direction>/", views.chapter_move, name="chapter_move"),
    # Entries
    path("trips/<int:pk>/entries/new/", views.entry_create, name="entry_create"),
    path("entries/<int:pk>/edit/", views.entry_edit, name="entry_edit"),
    path("entries/<int:pk>/delete/", views.entry_delete, name="entry_delete"),
    path("entries/<int:pk>/media-status/", media.media_status, name="media_status"),
    # Chunked uploads
    path("entries/<int:pk>/uploads/", media.upload_start, name="upload_start"),
    path("uploads/<uuid:upload_id>/", media.upload_status, name="upload_status"),
    path("uploads/<uuid:upload_id>/chunk/", media.upload_chunk, name="upload_chunk"),
    path("uploads/<uuid:upload_id>/complete/", media.upload_complete, name="upload_complete"),
    # Media items
    path("media-items/<int:pk>/delete/", media.media_delete, name="media_delete"),
    path("media-items/<int:pk>/move/<str:direction>/", media.media_move, name="media_move"),
    path("media-items/<int:pk>/cover/", media.media_cover, name="media_cover"),
    path("media-items/<int:pk>/retry/", media.media_retry, name="media_retry"),
    path("m/<int:pk>/<str:variant>/", media.serve_media, name="serve_media"),
    # Tracks
    path("trips/<int:pk>/tracks/new/", views.track_create, name="track_create"),
    path("tracks/<int:pk>/edit/", views.track_edit, name="track_edit"),
    path("tracks/<int:pk>/delete/", views.track_delete, name="track_delete"),
    # WhatsApp
    path("hooks/twilio/whatsapp/", whatsapp.twilio_webhook, name="twilio_webhook"),
    path("inbound/<int:pk>/assign/", views.inbound_assign, name="inbound_assign"),
    # Public share page and subscriptions
    path("s/<str:token>/", share.share_trip, name="share_trip"),
    path("s/<str:token>/map.json", share.share_map_data, name="share_map_data"),
    path("s/<str:token>/m/<int:pk>/<str:variant>/", media.share_media, name="share_media"),
    path("s/<str:token>/subscribe/", share.subscribe, name="subscribe"),
    path("subscribe/confirm/<str:token>/", share.subscription_confirm, name="subscription_confirm"),
    path("subscribe/unsubscribe/<str:token>/", share.subscription_unsubscribe,
         name="subscription_unsubscribe"),
]
