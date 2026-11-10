from django.conf import settings
from django.db import migrations


def everyone_travelled(apps, schema_editor):
    """Trips from before 'travellers' existed: both of us went."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Trip = apps.get_model("trips", "Trip")
    users = list(User.objects.filter(is_active=True))
    for trip in Trip.objects.all():
        trip.travellers.set(users)


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0002_media_location_source_trip_travellers_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(everyone_travelled, migrations.RunPython.noop)]
