from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import Invite, Profile


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["email", "invited_by", "trip", "created_at", "expires_at", "accepted_at"]
    readonly_fields = ["token"]


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class UserWithProfileAdmin(UserAdmin):
    inlines = [ProfileInline]
