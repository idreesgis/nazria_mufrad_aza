"""Patient registration and login with phone + password or Google (JWT), profile, password change, logout."""
from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
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

from . import google
from . import serializers as S
from .models import CONSENT_VERSION, PatientProfile, SocialAccount, role_of
from .permissions import HasAppKey
from .phone import normalize_phone
from .throttles import AuthRateThrottle

User = get_user_model()


def profile_of(user) -> dict:
    p = PatientProfile.objects.filter(user=user).first()
    return {"id": user.pk, "phone": (p.phone or None) if p else user.username, "email": user.email or "",
            "full_name": p.full_name if p else user.get_full_name(),
            "gender": p.gender if p else "", "birth_year": p.birth_year if p else None, "role": role_of(user),
            "consent_at": p.consent_at if p else None, "created_at": p.created_at if p else user.date_joined,
            "has_password": user.has_usable_password(),
            "linked_providers": sorted(SocialAccount.objects.filter(user=user).values_list("provider", flat=True))}


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
        with transaction.atomic():
            data.save()
            if "phone" in data.validated_data:       # a Google account adds its phone: phone login works from now on
                User.objects.filter(pk=request.user.pk).update(username=data.validated_data["phone"])
        audit(request, "profile.update", "user", request.user.pk, fields=sorted(data.validated_data))
        return Response(profile_of(request.user))


class PasswordView(APIView):
    """Change the password (all other sessions keep working until their tokens expire)."""
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.PasswordChangeIn, responses={204: None, 400: ErrorOut})
    def post(self, request):
        data = S.PasswordChangeIn(data=request.data)
        data.is_valid(raise_exception=True)
        first_password = not request.user.has_usable_password()     # Google account setting a password
        if not first_password and not request.user.check_password(data.validated_data.get("old_password") or ""):
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
        audit(request, "auth.password_set" if first_password else "auth.password_change", "user", request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------------------- Google sign-in
def _google_error(e: Exception) -> Response:
    if isinstance(e, google.GoogleUnavailable):
        return Response({"error": "google_unavailable", "detail": "Google could not be reached, try again later"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"error": "invalid_google_token", "detail": "the Google sign-in is invalid or expired, try again"},
                    status=status.HTTP_401_UNAUTHORIZED)


def _google_disabled() -> Response:
    return Response({"error": "google_login_disabled", "detail": "Google sign-in is not set up on this server"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)


def _unverified() -> Response:
    return Response({"error": "google_email_unverified", "detail": "this Google account's e-mail is not verified"},
                    status=status.HTTP_400_BAD_REQUEST)


class GoogleLoginView(APIView):
    """Sign in with Google. Send the ID token from Credential Manager / Google Sign-In.

    * A known Google account logs in (`200`, `created: false`).
    * An unknown one creates a patient account (`201`, `created: true`), which needs `consent: true`; without it the
      answer is `400 consent_required`: show the disclaimer and send the same request with `consent: true`.
    * Staff accounts cannot use Google: they log in with phone + password.
    """
    authentication_classes: list = []
    permission_classes = [HasAppKey]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.GoogleLoginIn, responses={200: S.GoogleTokensOut, 201: S.GoogleTokensOut, 400: ErrorOut,
                                                        401: ErrorOut, 403: ErrorOut, 503: ErrorOut}, auth=[])
    def post(self, request):
        if not google.enabled():
            return _google_disabled()
        data = S.GoogleLoginIn(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        try:
            ident = google.verify(d["id_token"])
        except (google.GoogleTokenInvalid, google.GoogleUnavailable) as e:
            audit(request, "auth.google_failed", "user", None, reason=type(e).__name__)
            return _google_error(e)
        if not ident.email_verified:
            audit(request, "auth.google_failed", "user", None, reason="email_unverified")
            return _unverified()

        link = SocialAccount.objects.select_related("user").filter(provider="google", uid=ident.sub).first()
        created = False
        if link is not None:
            user = link.user
            if not user.is_active:
                audit(request, "auth.google_failed", "user", user.pk, reason="inactive")
                return Response({"error": "account_disabled", "detail": "this account is disabled"}, status=403)
            if role_of(user) != "patient":
                audit(request, "auth.google_failed", "user", user.pk, reason="staff")
                return Response({"error": "staff_password_only", "detail": "staff log in with phone and password"},
                                status=403)
            SocialAccount.objects.filter(pk=link.pk).update(last_login_at=timezone.now(), email=ident.email,
                                                            email_verified=True, name=ident.name)
            if ident.email and user.email != ident.email:
                User.objects.filter(pk=user.pk).update(email=ident.email)
                user.email = ident.email
        else:
            if d.get("consent") is not True:
                audit(request, "auth.google_consent_required", "user", None)
                return Response({"error": "consent_required",
                                 "detail": "new account: show the disclaimer, then send consent: true"}, status=400)
            try:
                with transaction.atomic():
                    user = User(username=f"g_{ident.sub}"[:150], email=ident.email)
                    user.set_unusable_password()
                    user.save()
                    PatientProfile.objects.create(user=user, phone=None, full_name=d.get("full_name") or ident.name,
                                                  gender=d.get("gender") or "", birth_year=d.get("birth_year"),
                                                  consent_at=timezone.now(), consent_version=CONSENT_VERSION)
                    SocialAccount.objects.create(user=user, provider="google", uid=ident.sub, email=ident.email,
                                                 email_verified=True, name=ident.name, last_login_at=timezone.now())
                created = True
            except IntegrityError:                     # two first sign-ins at once: retry logs in
                return Response({"error": "retry", "detail": "please try again"}, status=status.HTTP_409_CONFLICT)
        audit(request, "auth.google_register" if created else "auth.google_login", "user", user.pk,
              provider="google", **({"consent_version": CONSENT_VERSION} if created else {}))
        request._request.audit_user = user
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        return Response({**tokens_for(user), "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GoogleLinkView(APIView):
    """POST: link a Google account to the logged-in patient (then they can sign in with either).
    DELETE: unlink it; only allowed when the account also has a phone and password, so nobody is locked out."""
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=S.GoogleLinkIn, responses={200: S.ProfileOut, 400: ErrorOut, 401: ErrorOut,
                                                       403: ErrorOut, 409: ErrorOut, 503: ErrorOut})
    def post(self, request):
        if not google.enabled():
            return _google_disabled()
        if role_of(request.user) != "patient":
            return Response({"error": "staff_password_only", "detail": "staff accounts cannot link Google"}, status=403)
        data = S.GoogleLinkIn(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            ident = google.verify(data.validated_data["id_token"])
        except (google.GoogleTokenInvalid, google.GoogleUnavailable) as e:
            audit(request, "auth.google_link_failed", "user", request.user.pk, reason=type(e).__name__)
            return _google_error(e)
        if not ident.email_verified:
            return _unverified()
        other = SocialAccount.objects.filter(provider="google", uid=ident.sub).first()
        if other is not None and other.user_id != request.user.pk:
            audit(request, "auth.google_link_failed", "user", request.user.pk, reason="linked_elsewhere")
            return Response({"error": "google_already_linked",
                             "detail": "this Google account belongs to another Nazria account"}, status=409)
        mine = SocialAccount.objects.filter(user=request.user, provider="google").first()
        if mine is not None and mine.uid != ident.sub:
            return Response({"error": "google_already_linked",
                             "detail": "a different Google account is already linked; unlink it first"}, status=409)
        if mine is None:
            SocialAccount.objects.create(user=request.user, provider="google", uid=ident.sub, email=ident.email,
                                         email_verified=True, name=ident.name)
        if ident.email and not request.user.email:
            User.objects.filter(pk=request.user.pk).update(email=ident.email)
            request.user.email = ident.email
        audit(request, "auth.google_link", "user", request.user.pk, provider="google")
        return Response(profile_of(request.user))

    @extend_schema(responses={200: S.ProfileOut, 404: ErrorOut, 409: ErrorOut})
    def delete(self, request):
        mine = SocialAccount.objects.filter(user=request.user, provider="google").first()
        if mine is None:
            return Response({"error": "not_found", "detail": "no Google account is linked"}, status=404)
        p = PatientProfile.objects.filter(user=request.user).first()
        if not request.user.has_usable_password() or not (p and p.phone):
            return Response({"error": "last_login_method",
                             "detail": "add a phone number and a password before unlinking Google"}, status=409)
        mine.delete()
        audit(request, "auth.google_unlink", "user", request.user.pk, provider="google")
        return Response(profile_of(request.user))
