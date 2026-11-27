"""Patients log in with their phone number (the Django username is the canonical phone number) or with Google
(``SocialAccount``; a Google-only patient has no phone until they add one).
Staff (Hakeem, admin) are Django users with is_staff, in the group "hakeem" (or superusers)."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone

HAKEEM_GROUP = "hakeem"
CONSENT_VERSION = "2026-11"          # bump when the consent / disclaimer text the app shows changes


class PatientProfile(models.Model):
    GENDERS = [("male", "male"), ("female", "female"), ("other", "other")]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="profile")
    phone = models.CharField(max_length=16, unique=True, null=True, blank=True,
                             help_text="+92…; empty for an account created with Google until the patient adds one")
    full_name = models.CharField(max_length=150, blank=True)
    gender = models.CharField(max_length=10, choices=GENDERS, blank=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True, help_text="when the patient accepted the disclaimer")
    consent_version = models.CharField(max_length=20, blank=True)
    language = models.CharField(max_length=2, choices=[("ur", "اردو"), ("en", "English"), ("ar", "العربية")],
                                default="ur", help_text="language of the app's texts for this user")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.phone or ''} {self.full_name}".strip()


class SocialAccount(models.Model):
    """A Google (or later another provider's) identity linked to a user. ``uid`` is the provider's stable user id
    (Google's ``sub``), never the e-mail address, which can change."""
    PROVIDERS = [("google", "Google")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="social_accounts")
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    uid = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    email_verified = models.BooleanField(default=False)
    name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "uid"], name="social_provider_uid_unique"),
                       models.UniqueConstraint(fields=["user", "provider"], name="social_user_provider_unique")]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider}: {self.email or self.uid}"


def role_of(user) -> str:
    """admin | hakeem | patient"""
    if user.is_superuser:
        return "admin"
    if user.is_staff or user.groups.filter(name=HAKEEM_GROUP).exists():
        return "hakeem"
    return "patient"


def is_staff_user(user) -> bool:
    return bool(user and user.is_authenticated and role_of(user) in ("admin", "hakeem"))


def hakeem_group() -> Group:
    return Group.objects.get_or_create(name=HAKEEM_GROUP)[0]
