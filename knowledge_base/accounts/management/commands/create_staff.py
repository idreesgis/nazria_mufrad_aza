"""python manage.py create_staff --phone 03001234567 --name "Hakeem Ahmad" [--admin]
Creates a Hakeem (or admin) account who logs in with the phone number; the password is asked interactively
(or read from the environment variable named by --password-env, for scripts)."""
import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import PatientProfile, hakeem_group
from accounts.phone import normalize_phone


class Command(BaseCommand):
    help = "Create a Hakeem / admin account that logs in with a phone number."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--name", default="")
        parser.add_argument("--admin", action="store_true", help="superuser (full admin rights)")
        parser.add_argument("--password-env", help="NAME of an environment variable holding the password")

    def handle(self, *args, phone, name, admin, password_env, **options):
        try:
            phone = normalize_phone(phone)
        except ValueError:
            raise CommandError("not a valid phone number") from None
        User = get_user_model()
        if User.objects.filter(username=phone).exists():
            raise CommandError(f"{phone} already has an account")
        password = os.environ.get(password_env, "") if password_env else getpass.getpass("Password: ")
        user = User(username=phone, first_name=name)
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages)) from None
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = admin
        user.save()
        user.groups.add(hakeem_group())
        PatientProfile.objects.create(user=user, phone=phone, full_name=name)
        self.stdout.write(f"{'admin' if admin else 'hakeem'} account created for {phone}")
