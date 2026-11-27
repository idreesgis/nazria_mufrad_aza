"""Patients log in with their phone number (the Django username is the canonical phone number).
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
    phone = models.CharField(max_length=16, unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    gender = models.CharField(max_length=10, choices=GENDERS, blank=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True, help_text="when the patient accepted the disclaimer")
    consent_version = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.phone} {self.full_name}".strip()


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
