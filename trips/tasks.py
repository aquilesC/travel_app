"""Background tasks, run by the `worker` container (django-tasks-db).

Kept thin: each task delegates to a plain function that tests can call directly.
"""

from django.tasks import task


@task
def nightly_backup():
    from .backup import dump_database
    from .services.uploads import delete_stale_uploads

    delete_stale_uploads()  # nightly housekeeping rides along with the backup
    return str(dump_database())


@task
def process_media(media_id):
    from .processing import process

    process(media_id)


@task
def process_inbound(message_id, trip_id=None):
    from .whatsapp import process_message

    process_message(message_id, trip_id=trip_id)


@task
def send_subscription_confirmation(subscriber_id):
    from .digest import send_confirmation

    send_confirmation(subscriber_id)


@task
def send_daily_digests():
    from .digest import send_digests

    return send_digests()
