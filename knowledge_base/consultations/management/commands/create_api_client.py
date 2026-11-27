"""python manage.py create_api_client "android-app" – prints the new API key once (store it in the app build)."""
from django.core.management.base import BaseCommand, CommandError

from consultations.models import ApiClient


class Command(BaseCommand):
    help = "Create an API client and print its key (shown only once; only a hash is stored)."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--notes", default="")

    def handle(self, *args, name, notes, **options):
        if ApiClient.objects.filter(name=name).exists():
            raise CommandError(f"an API client named {name!r} already exists (revoke it in the admin first)")
        client, key = ApiClient.create(name, notes)
        self.stdout.write(f"API client {client.name!r} created. Key (copy it now, it is not shown again):")
        self.stdout.write(key)
