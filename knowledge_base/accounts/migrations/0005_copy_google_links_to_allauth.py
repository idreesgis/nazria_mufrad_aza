"""Copies the Google links of accounts.SocialAccount into allauth's socialaccount.SocialAccount (same provider "google"
and the same Google user id), so every Google patient keeps signing in after the move to django-allauth.

The old table is kept unchanged (nothing is deleted); the API no longer reads or writes it.
Running it again copies nothing twice (provider + uid are unique in allauth)."""
from django.db import migrations


def copy_links(apps, schema_editor):
    Old = apps.get_model("accounts", "SocialAccount")
    New = apps.get_model("socialaccount", "SocialAccount")
    for old in Old.objects.all().iterator():
        if New.objects.filter(provider=old.provider, uid=old.uid).exists():
            continue
        new = New.objects.create(user_id=old.user_id, provider=old.provider, uid=old.uid,
                                 extra_data={"sub": old.uid, "email": old.email, "email_verified": old.email_verified,
                                             "name": old.name})
        # date_joined / last_login are auto fields in allauth: set them to the original times afterwards
        New.objects.filter(pk=new.pk).update(date_joined=old.created_at,
                                             last_login=old.last_login_at or old.created_at)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_user_language"),
        ("socialaccount", "0006_alter_socialaccount_extra_data"),
    ]
    operations = [
        migrations.AlterModelOptions(name="socialaccount",
                                     options={"ordering": ["-created_at"], "verbose_name": "Google link (before allauth)"}),
        migrations.RunPython(copy_links, migrations.RunPython.noop),
    ]
