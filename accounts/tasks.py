from django.tasks import task


@task
def send_invite_email(invite_id):
    from .invites import inviter_name, send_mail_template
    from .models import Invite

    invite = Invite.objects.select_related("trip", "invited_by").get(pk=invite_id)
    if invite.accepted_at:
        return
    name = inviter_name(invite.invited_by)
    subject = f"{name} invited you to {invite.trip.title if invite.trip else 'Trips'}"
    send_mail_template(invite.email, subject, "invite", {"invite": invite, "inviter": name})


@task
def send_added_email(user_id, trip_id, inviter_id):
    from django.conf import settings
    from django.contrib.auth import get_user_model

    from trips.models import Trip

    from .invites import inviter_name, send_mail_template

    User = get_user_model()
    user, inviter = User.objects.get(pk=user_id), User.objects.get(pk=inviter_id)
    trip = Trip.objects.get(pk=trip_id)
    send_mail_template(user.email, f"{inviter_name(inviter)} added you to {trip.title}", "added", {
        "inviter": inviter_name(inviter), "trip": trip,
        "trip_url": settings.SITE_URL + trip.get_absolute_url(),
    })
