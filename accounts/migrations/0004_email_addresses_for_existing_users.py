from django.conf import settings
from django.db import migrations


def add_email_addresses(apps, schema_editor):
    """allauth logs in by EmailAddress: give existing users a verified primary one."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    EmailAddress = apps.get_model("account", "EmailAddress")
    for user in User.objects.exclude(email=""):
        EmailAddress.objects.get_or_create(
            user=user, email=user.email.lower(), defaults={"verified": True, "primary": True}
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_profile_avatar_profile_is_public_and_more"),
        ("account", "__latest__"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(add_email_addresses, migrations.RunPython.noop)]
