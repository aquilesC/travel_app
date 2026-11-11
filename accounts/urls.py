from django.urls import path

from . import views

urlpatterns = [
    path("account/", views.account, name="account"),
    path("account/picture/remove/", views.avatar_remove, name="avatar_remove"),
    path("invites/", views.invites, name="invites"),
    path("invites/<int:pk>/resend/", views.invite_resend, name="invite_resend"),
    path("invites/<int:pk>/revoke/", views.invite_revoke, name="invite_revoke"),
    path("invite/<str:token>/", views.invite_accept, name="invite_accept"),
    path("u/<str:username>/", views.public_profile, name="public_profile"),
    path("u/<str:username>/avatar/", views.public_avatar, name="public_avatar"),
]
