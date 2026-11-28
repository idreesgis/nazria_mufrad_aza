from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import PatientProfile
from .phone import normalize_phone

User = get_user_model()


def _phone(value: str) -> str:
    try:
        return normalize_phone(value)
    except ValueError:
        raise serializers.ValidationError("not a valid phone number") from None


class RegisterIn(serializers.Serializer):
    phone = serializers.CharField(max_length=30, help_text="Any common format: 0300-1234567, +923001234567 …")
    password = serializers.CharField(write_only=True, min_length=8, max_length=128, style={"input_type": "password"})
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    gender = serializers.ChoiceField(choices=["male", "female", "other"], required=False, allow_blank=True)
    birth_year = serializers.IntegerField(min_value=1900, max_value=2100, required=False, allow_null=True)
    consent = serializers.BooleanField(help_text="The patient accepted the disclaimer (guidance, not diagnosis)")
    language = serializers.ChoiceField(choices=["ur", "en", "ar"], required=False, help_text="Language of the app's texts: ur | en | ar")

    def validate_phone(self, value):
        phone = _phone(value)
        if User.objects.filter(username=phone).exists():
            raise serializers.ValidationError("an account with this phone number already exists")
        return phone

    def validate_consent(self, value):
        if value is not True:
            raise serializers.ValidationError("the disclaimer must be accepted")
        return value

    def validate(self, data):
        try:
            validate_password(data["password"], User(username=data["phone"], first_name=data.get("full_name", "")))
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": " ".join(e.messages)}) from None
        return data


class LoginIn(serializers.Serializer):
    phone = serializers.CharField(max_length=30)
    password = serializers.CharField(write_only=True, max_length=128, style={"input_type": "password"})


class RefreshIn(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordChangeIn(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, max_length=128, required=False, allow_blank=True,
                                         help_text="Required, except for a social-login account that has no password yet")
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=128)


class ProfileOut(serializers.Serializer):
    id = serializers.IntegerField()
    phone = serializers.CharField(allow_null=True, help_text="null for a social-login account until the patient adds one")
    email = serializers.CharField(allow_blank=True, help_text="From the linked provider (Google, Facebook, Apple, Microsoft), if any")
    full_name = serializers.CharField()
    gender = serializers.CharField()
    birth_year = serializers.IntegerField(allow_null=True)
    role = serializers.ChoiceField(choices=["patient", "hakeem", "admin"])
    consent_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    has_password = serializers.BooleanField(help_text="False for a social-login-only account (phone login not possible)")
    language = serializers.ChoiceField(choices=["ur", "en", "ar"])
    linked_providers = serializers.ListField(child=serializers.CharField(), help_text='Any of google, facebook, apple, microsoft')


class ProfileIn(serializers.ModelSerializer):
    phone = serializers.CharField(max_length=30, required=False,
                                  help_text="Only accepted while the account has no phone yet (social-login accounts)")

    class Meta:
        model = PatientProfile
        fields = ["full_name", "gender", "birth_year", "phone", "language"]
        extra_kwargs = {"birth_year": {"min_value": 1900, "max_value": 2100}}

    def validate_phone(self, value):
        if self.instance is not None and self.instance.phone:
            raise serializers.ValidationError("the phone number cannot be changed; ask the clinic staff")
        phone = _phone(value)
        if User.objects.filter(username=phone).exists() or PatientProfile.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("an account with this phone number already exists")
        return phone


_TOKEN_HELP = ("google: id_token (Credential Manager, serverClientId = the server's Web client ID) · "
               "facebook: access_token (Facebook Login SDK) · apple: id_token + nonce · "
               "microsoft: id_token (AppAuth, authorization code + PKCE)")


class SocialTokenIn(serializers.Serializer):
    id_token = serializers.CharField(max_length=8192, required=False, write_only=True, help_text=_TOKEN_HELP)
    access_token = serializers.CharField(max_length=4096, required=False, write_only=True,
                                         help_text="Facebook only: the access token from the Facebook Login SDK")
    nonce = serializers.CharField(max_length=256, required=False, write_only=True,
                                  help_text="Apple only: the raw nonce; its SHA-256 (hex) was sent to Apple")

    def validate(self, attrs):
        if not attrs.get("id_token") and not attrs.get("access_token") and not attrs.get("signup_token"):
            raise serializers.ValidationError({"id_token": "send the provider's id_token or access_token"})
        return attrs


class SocialLoginIn(SocialTokenIn):
    signup_token = serializers.CharField(max_length=4096, required=False, write_only=True,
                                         help_text="From a 400 consent_required answer: send it back (instead of the "
                                                   "provider token) with consent: true to create the account")
    consent = serializers.BooleanField(required=False, default=False,
                                       help_text="Needed (true) only when a new account is created")
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True,
                                      help_text="New accounts: defaults to the name from the provider")
    gender = serializers.ChoiceField(choices=["male", "female", "other"], required=False, allow_blank=True)
    birth_year = serializers.IntegerField(min_value=1900, max_value=2100, required=False, allow_null=True)
    language = serializers.ChoiceField(choices=["ur", "en", "ar"], required=False,
                                       help_text="Language of the app's texts: ur | en | ar")


class SocialLinkIn(SocialTokenIn):
    pass


class GoogleLoginIn(SocialLoginIn):
    """The older Google-only route (same as /auth/social/google/)."""


class GoogleLinkIn(SocialLinkIn):
    pass


class TokensOut(serializers.Serializer):
    access = serializers.CharField(help_text="Send as Authorization: Bearer <access> (valid 30 minutes)")
    refresh = serializers.CharField(help_text="Exchange at /auth/refresh/ for new tokens (valid 30 days)")
    user = ProfileOut()


class SocialTokensOut(TokensOut):
    created = serializers.BooleanField(help_text="True when this sign-in created a new account")
    provider = serializers.ChoiceField(choices=["google", "facebook", "apple", "microsoft"])


GoogleTokensOut = SocialTokensOut
