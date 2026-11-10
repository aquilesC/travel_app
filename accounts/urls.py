from django.urls import path

from . import views

urlpatterns = [
    path("account/", views.account, name="account"),
    path("account/picture/remove/", views.avatar_remove, name="avatar_remove"),
    path("u/<str:username>/", views.public_profile, name="public_profile"),
    path("u/<str:username>/avatar/", views.public_avatar, name="public_avatar"),
]
