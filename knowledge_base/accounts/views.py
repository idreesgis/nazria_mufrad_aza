"""Patient registration and login with phone + password (JWT), profile, password change, logout."""
from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from audit.middleware import audit
from consultations.serializers import ErrorOut

from . import serializers as S
from .models import CONSENT_VERSION, PatientProfile, role_of
from .permissions import HasAppKey
from .phone import normalize_phone
from .throttles import AuthRateThrottle

User = get_user_model()


def profile_of(user) -> dict:
    p = PatientProfile.objects.filter(user=user).first()
    return {"id": user.pk, "phone": p.phone if p else user.username, "full_name": p.full_name if p else user.get_full_name(),
            "gender": p.gender if p else "", "birth_year": p.birth_year if p else None, "role": role_of(user),
            "consent_at": p.consent_at if p else None, "created_at": p.created_at if p else user.date_joined}


def tokens_for(user) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = role_of(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh), "user": profile_of(user)}


class RegisterView(APIView):
    """Create a patient account (phone + password) and log in."""
    authentication_classes: list = []
    permission_classes = [HasAppKey]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.RegisterIn, responses={201: S.TokensOut, 400: ErrorOut}, auth=[])
    def post(self, request):
        data = S.RegisterIn(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        with transaction.atomic():
            user = User.objects.create_user(username=d["phone"], password=d["password"])
            PatientProfile.objects.create(user=user, phone=d["phone"], full_name=d.get("full_name") or "",
                                          gender=d.get("gender") or "", birth_year=d.get("birth_year"),
                                          consent_at=timezone.now(), consent_version=CONSENT_VERSION)
        audit(request, "auth.register", "user", user.pk, consent_version=CONSENT_VERSION)
        request._request.audit_user = user
        return Response(tokens_for(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Log in with phone + password: returns an access token (30 min) and a refresh token (30 days)."""
    authentication_classes: list = []
    permission_classes = [HasAppKey]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.LoginIn, responses={200: S.TokensOut, 401: ErrorOut}, auth=[])
    def post(self, request):
        data = S.LoginIn(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            phone = normalize_phone(data.validated_data["phone"])
        except ValueError:
            phone = None
        user = authenticate(request, username=phone, password=data.validated_data["password"]) if phone else None
        if user is None:
            audit(request, "auth.login_failed", "user", None, phone=phone or "invalid")
            return Response({"error": "invalid_credentials", "detail": "phone number or password is wrong"},
                            status=status.HTTP_401_UNAUTHORIZED)
        audit(request, "auth.login", "user", user.pk)
        request._request.audit_user = user
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        return Response(tokens_for(user))


class RefreshView(APIView):
    """New access + refresh tokens for a valid refresh token (the old refresh token stops working)."""
    authentication_classes: list = []
    permission_classes = [HasAppKey]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.RefreshIn, responses={200: S.TokensOut, 401: ErrorOut}, auth=[])
    def post(self, request):
        data = S.RefreshIn(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            old = RefreshToken(data.validated_data["refresh"])
            user = User.objects.get(pk=old["user_id"], is_active=True)
            old.blacklist()
        except (TokenError, User.DoesNotExist, KeyError):
            audit(request, "auth.refresh_failed")
            return Response({"error": "invalid_token", "detail": "the refresh token is invalid or expired, log in again"},
                            status=status.HTTP_401_UNAUTHORIZED)
        audit(request, "auth.refresh", "user", user.pk)
        request._request.audit_user = user
        return Response(tokens_for(user))


class LogoutView(APIView):
    """Invalidate a refresh token (log out on this phone)."""
    permission_classes = [HasAppKey, IsAuthenticated]

    @extend_schema(request=S.RefreshIn, responses={204: None, 400: ErrorOut})
    def post(self, request):
        data = S.RefreshIn(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            token = RefreshToken(data.validated_data["refresh"])
            if str(token["user_id"]) != str(request.user.pk):
                raise TokenError("not this user's token")
            token.blacklist()
        except (TokenError, KeyError):
            return Response({"error": "invalid_token", "detail": "invalid refresh token"}, status=400)
        audit(request, "auth.logout", "user", request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """The logged-in user's profile; PATCH changes name, gender or birth year."""

    @extend_schema(responses={200: S.ProfileOut})
    def get(self, request):
        return Response(profile_of(request.user))

    @extend_schema(request=S.ProfileIn, responses={200: S.ProfileOut, 400: ErrorOut})
    def patch(self, request):
        profile, _ = PatientProfile.objects.get_or_create(user=request.user, defaults={"phone": request.user.username})
        data = S.ProfileIn(profile, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        data.save()
        audit(request, "profile.update", "user", request.user.pk, fields=sorted(data.validated_data))
        return Response(profile_of(request.user))


class PasswordView(APIView):
    """Change the password (all other sessions keep working until their tokens expire)."""
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.PasswordChangeIn, responses={204: None, 400: ErrorOut})
    def post(self, request):
        data = S.PasswordChangeIn(data=request.data)
        data.is_valid(raise_exception=True)
        if not request.user.check_password(data.validated_data["old_password"]):
            audit(request, "auth.password_change_failed", "user", request.user.pk)
            return Response({"error": "invalid_credentials", "detail": "the current password is wrong"}, status=400)
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(data.validated_data["new_password"], request.user)
        except ValidationError as e:
            return Response({"error": "invalid_request", "detail": "the new password is not allowed",
                             "fields": {"new_password": " ".join(e.messages)}}, status=400)
        request.user.set_password(data.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        audit(request, "auth.password_change", "user", request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
