"""Patient registration and login with phone + password or Google, Facebook, Apple, Microsoft (JWT), profile, password change, logout."""
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

from allauth.socialaccount.models import SocialAccount as SocialLink

from . import serializers as S
from . import social
from .models import CONSENT_VERSION, PatientProfile, role_of
from .permissions import HasAppKey
from .phone import normalize_phone
from .throttles import AuthRateThrottle
from nazria_api.language import request_language

User = get_user_model()


def profile_of(user) -> dict:
    p = PatientProfile.objects.filter(user=user).first()
    return {"id": user.pk, "phone": (p.phone or None) if p else user.username, "email": user.email or "",
            "full_name": p.full_name if p else user.get_full_name(),
            "gender": p.gender if p else "", "birth_year": p.birth_year if p else None, "role": role_of(user),
            "consent_at": p.consent_at if p else None, "created_at": p.created_at if p else user.date_joined,
            "has_password": user.has_usable_password(), "language": (p.language if p else None) or "ur",
            "linked_providers": sorted(SocialLink.objects.filter(user=user).values_list("provider", flat=True))}


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
                                          consent_at=timezone.now(), consent_version=CONSENT_VERSION,
                                          language=d.get("language") or request_language(request))
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
            if "phone" in data.validated_data:       # a social-login account adds its phone: phone login works from now on
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
        first_password = not request.user.has_usable_password()     # social-login account setting a password
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


# ------------------------------------------------------------------------------------------- social sign-in
# The older Google-only routes (/auth/google/, /me/google/) answer with their original error codes.
_LEGACY_GOOGLE_CODES = {"provider_disabled": "google_login_disabled", "invalid_social_token": "invalid_google_token",
                        "provider_unavailable": "google_unavailable", "email_unverified": "google_email_unverified",
                        "social_already_linked": "google_already_linked"}


def _err(code: str, detail: str, http: int, legacy: bool, **extra) -> Response:
    return Response({"error": _LEGACY_GOOGLE_CODES.get(code, code) if legacy else code, "detail": detail, **extra},
                    status=http)


def _check_provider(provider: str, legacy: bool) -> Response | None:
    if provider not in social.PROVIDERS:
        return Response({"error": "not_found", "detail": "unknown sign-in provider"}, status=404)
    if not social.enabled(provider):
        return _err("provider_disabled", f"{social.NAMES[provider]} sign-in is not set up on this server", 503, legacy)
    return None


def _verify(request, provider: str, d: dict, legacy: bool, action: str, user_id=None):
    """(identity, None) or (None, error response)."""
    token = {k: d[k] for k in ("id_token", "access_token", "nonce") if d.get(k)}
    name = social.NAMES[provider]
    try:
        ident = social.verify(request, provider, token)
    except social.ProviderDisabled:
        return None, _check_provider(provider, legacy)
    except social.SocialUnavailable:
        audit(request, action, "user", user_id, provider=provider, reason="unavailable")
        return None, _err("provider_unavailable", f"{name} could not be reached, try again later", 503, legacy)
    except social.SocialTokenInvalid:
        audit(request, action, "user", user_id, provider=provider, reason="invalid_token")
        return None, _err("invalid_social_token", f"the {name} sign-in is invalid or expired, try again", 401, legacy)
    if provider == "google" and not ident.email_verified:      # as before the move to allauth
        audit(request, action, "user", user_id, provider=provider, reason="email_unverified")
        return None, _err("email_unverified", "this Google account's e-mail is not verified", 400, legacy)
    return ident, None


def _create_account(request, ident: social.SocialIdentity, d: dict):
    with transaction.atomic():
        user = User(username=f"{ident.provider[0]}_{ident.uid}"[:150], email=ident.email)
        user.set_unusable_password()
        user.save()
        PatientProfile.objects.create(user=user, phone=None, full_name=d.get("full_name") or ident.name,
                                      gender=d.get("gender") or "", birth_year=d.get("birth_year"),
                                      consent_at=timezone.now(), consent_version=CONSENT_VERSION,
                                      language=d.get("language") or request_language(request))
        SocialLink.objects.create(user=user, provider=ident.provider, uid=ident.uid, extra_data=_extra(ident))
    return user


def _extra(ident: social.SocialIdentity) -> dict:
    """What allauth keeps about the provider account: e-mail and name only (no tokens, no photo)."""
    return {"email": ident.email, "email_verified": ident.email_verified, "name": ident.name,
            **({"tid": ident.extra["tid"]} if "tid" in ident.extra else {})}


class SocialLoginView(APIView):
    """Sign in with Google, Facebook, Apple or Microsoft (`provider` in the URL).

    Send what the provider's SDK gave the app: `id_token` (Google, Apple + `nonce`, Microsoft) or `access_token`
    (Facebook). GET /health/ lists the providers that are on (`social_providers`) and their public IDs.

    * A known provider account logs in (`200`, `created: false`).
    * An unknown one creates a patient account (`201`, `created: true`), which needs the patient's consent: the first
      answer is `400 consent_required` with a `signup_token`. Show the disclaimer, then send `signup_token` (not the
      provider token again) with `consent: true`.
    * Accounts are never matched by e-mail address. To add a provider to an existing account, log in and use
      `POST /me/social/<provider>/`.
    * Staff accounts cannot use social sign-in: they log in with phone + password.
    """
    authentication_classes: list = []
    permission_classes = [HasAppKey]
    throttle_classes = [AuthRateThrottle]
    legacy = False

    @extend_schema(request=S.SocialLoginIn, responses={200: S.SocialTokensOut, 201: S.SocialTokensOut, 400: ErrorOut,
                                                        401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut,
                                                        503: ErrorOut}, auth=[])
    def post(self, request, provider: str = "google"):
        if (bad := _check_provider(provider, self.legacy)) is not None:
            return bad
        data = S.SocialLoginIn(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        if d.get("signup_token"):
            try:
                ident = social.from_signup_token(d["signup_token"], provider)
            except social.SocialTokenInvalid:
                audit(request, "auth.social_failed", "user", None, provider=provider, reason="signup_token")
                return _err("invalid_social_token", "the sign-up has expired, sign in again", 401, self.legacy)
        else:
            ident, error = _verify(request, provider, d, self.legacy, "auth.social_failed")
            if error is not None:
                return error

        link = SocialLink.objects.select_related("user").filter(provider=provider, uid=ident.uid).first()
        created = False
        if link is not None:
            user = link.user
            if not user.is_active:
                audit(request, "auth.social_failed", "user", user.pk, provider=provider, reason="inactive")
                return Response({"error": "account_disabled", "detail": "this account is disabled"}, status=403)
            if role_of(user) != "patient":
                audit(request, "auth.social_failed", "user", user.pk, provider=provider, reason="staff")
                return Response({"error": "staff_password_only", "detail": "staff log in with phone and password"},
                                status=403)
            SocialLink.objects.filter(pk=link.pk).update(last_login=timezone.now(),
                                                         extra_data={**(link.extra_data or {}), **_extra(ident)})
            if ident.email and ident.email_verified and user.email != ident.email:
                User.objects.filter(pk=user.pk).update(email=ident.email)
                user.email = ident.email
        else:
            if d.get("consent") is not True:
                audit(request, "auth.social_consent_required", "user", None, provider=provider)
                return Response({"error": "consent_required", "signup_token": social.signup_token(ident),
                                 "detail": "new account: show the disclaimer, then send signup_token with consent: true"},
                                status=400)
            try:
                user = _create_account(request, ident, d)
                created = True
            except IntegrityError:                     # two first sign-ins at once: retry logs in
                return Response({"error": "retry", "detail": "please try again"}, status=status.HTTP_409_CONFLICT)
        audit(request, "auth.social_register" if created else "auth.social_login", "user", user.pk,
              provider=provider, **({"consent_version": CONSENT_VERSION} if created else {}))
        request._request.audit_user = user
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        return Response({**tokens_for(user), "created": created, "provider": provider},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GoogleLoginView(SocialLoginView):
    """Sign in with Google: the older route, the same as `POST /auth/social/google/`."""
    legacy = True

    @extend_schema(request=S.GoogleLoginIn, responses={200: S.SocialTokensOut, 201: S.SocialTokensOut,
                                                        400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 503: ErrorOut},
                   auth=[], operation_id="auth_google_create")
    def post(self, request):
        return super().post(request, "google")


def _login_methods_left(user, without_provider: str) -> bool:
    p = PatientProfile.objects.filter(user=user).first()
    if user.has_usable_password() and p and p.phone:
        return True
    return SocialLink.objects.filter(user=user).exclude(provider=without_provider).exists()


class SocialLinkView(APIView):
    """POST: link a Google, Facebook, Apple or Microsoft account to the logged-in patient (then they can sign in with
    it too); send the same token fields as for sign-in. DELETE: unlink it; refused when it is the account's last way
    to log in (no phone + password and no other linked provider), so nobody is locked out."""
    throttle_classes = [AuthRateThrottle]
    legacy = False

    @extend_schema(request=S.SocialLinkIn, responses={200: S.ProfileOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut,
                                                       404: ErrorOut, 409: ErrorOut, 503: ErrorOut})
    def post(self, request, provider: str = "google"):
        if (bad := _check_provider(provider, self.legacy)) is not None:
            return bad
        name = social.NAMES[provider]
        if role_of(request.user) != "patient":
            return Response({"error": "staff_password_only", "detail": f"staff accounts cannot link {name}"},
                            status=403)
        data = S.SocialLinkIn(data=request.data)
        data.is_valid(raise_exception=True)
        ident, error = _verify(request, provider, data.validated_data, self.legacy, "auth.social_link_failed",
                               request.user.pk)
        if error is not None:
            return error
        other = SocialLink.objects.filter(provider=provider, uid=ident.uid).first()
        if other is not None and other.user_id != request.user.pk:
            audit(request, "auth.social_link_failed", "user", request.user.pk, provider=provider,
                  reason="linked_elsewhere")
            return _err("social_already_linked", f"this {name} account belongs to another Nazria account", 409,
                        self.legacy)
        mine = SocialLink.objects.filter(user=request.user, provider=provider).first()
        if mine is not None and mine.uid != ident.uid:
            return _err("social_already_linked", f"a different {name} account is already linked; unlink it first",
                        409, self.legacy)
        if mine is None:
            try:
                SocialLink.objects.create(user=request.user, provider=provider, uid=ident.uid, extra_data=_extra(ident))
            except IntegrityError:
                return Response({"error": "retry", "detail": "please try again"}, status=status.HTTP_409_CONFLICT)
        if ident.email and ident.email_verified and not request.user.email:
            User.objects.filter(pk=request.user.pk).update(email=ident.email)
            request.user.email = ident.email
        audit(request, "auth.social_link", "user", request.user.pk, provider=provider)
        return Response(profile_of(request.user))

    @extend_schema(responses={200: S.ProfileOut, 404: ErrorOut, 409: ErrorOut})
    def delete(self, request, provider: str = "google"):
        if provider not in social.PROVIDERS:
            return Response({"error": "not_found", "detail": "unknown sign-in provider"}, status=404)
        name = social.NAMES[provider]
        mine = SocialLink.objects.filter(user=request.user, provider=provider).first()
        if mine is None:
            return Response({"error": "not_found", "detail": f"no {name} account is linked"}, status=404)
        if not _login_methods_left(request.user, provider):
            return Response({"error": "last_login_method",
                             "detail": f"add a phone number and a password, or link another account, before "
                                       f"unlinking {name}"}, status=409)
        mine.delete()
        audit(request, "auth.social_unlink", "user", request.user.pk, provider=provider)
        return Response(profile_of(request.user))


class GoogleLinkView(SocialLinkView):
    """The older route, the same as `/me/social/google/`."""
    legacy = True

    @extend_schema(request=S.GoogleLinkIn, responses={200: S.ProfileOut, 400: ErrorOut, 401: ErrorOut,
                                                       403: ErrorOut, 409: ErrorOut, 503: ErrorOut},
                   operation_id="me_google_create")
    def post(self, request):
        return super().post(request, "google")

    @extend_schema(responses={200: S.ProfileOut, 404: ErrorOut, 409: ErrorOut}, operation_id="me_google_destroy")
    def delete(self, request):
        return super().delete(request, "google")
