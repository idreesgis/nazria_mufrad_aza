import pytest
from rest_framework.test import APIClient

from consultations import services
from consultations.backends import MemoryKnowledgeBase, set_knowledge_base
from consultations.models import ApiClient


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, settings):
    for k in ("NAZRIA_ENGINE", "NAZRIA_LLM_PROVIDER", "NAZRIA_LLM_MODEL", "NAZRIA_ALLOW_EXTERNAL_PROVIDERS"):
        monkeypatch.delenv(k, raising=False)
    from django.core.cache import cache
    cache.clear()
    kb = MemoryKnowledgeBase()
    set_knowledge_base(kb)
    services.set_provider(None)
    yield kb
    set_knowledge_base(None)
    services.set_provider(None)


@pytest.fixture
def kb(_fresh):
    return _fresh


@pytest.fixture
def app_key(db):
    return ApiClient.create("android-test")[1]


@pytest.fixture
def anon(app_key):
    """The app before login: app key only."""
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=app_key)
    return c


def make_user(phone="+923001234567", password="sabz-chai-2026", name="Test Patient", staff=False, admin=False):
    from django.contrib.auth import get_user_model

    from accounts.models import PatientProfile, hakeem_group
    user = get_user_model().objects.create_user(username=phone, password=password, is_staff=staff or admin,
                                                is_superuser=admin)
    if staff or admin:
        user.groups.add(hakeem_group())
    PatientProfile.objects.create(user=user, phone=phone, full_name=name)
    return user


def make_patient(account, full_name="Test Patient", relation="self", gender="male", birth_year=1985, **extra):
    from django.utils import timezone

    from patients.models import Patient, record_revision
    p = Patient.objects.create(account=account, full_name=full_name, relation=relation, gender=gender,
                               birth_year=birth_year, consent_at=timezone.now(), **extra)
    record_revision(p, account, "created")
    return p


def logged_in(app_key, user) -> APIClient:
    """A logged-in client; ``c.patient`` is a default adult male patient of the account (relation "self")."""
    from accounts.views import tokens_for
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=app_key, HTTP_AUTHORIZATION=f"Bearer {tokens_for(user)['access']}")
    c.user = user
    c.patient = make_patient(user)
    return c


@pytest.fixture
def patient_user(db):
    return make_user()


@pytest.fixture
def api(app_key, patient_user):
    """A logged-in patient."""
    return logged_in(app_key, patient_user)


@pytest.fixture
def hakeem(app_key, db):
    return logged_in(app_key, make_user("+923331112223", name="Hakeem Sahib", staff=True))


# the reference consultation of the CLI: chronic constipation, adult, muscular signs
REFERENCE = {"red_flags": ["none"], "complaint": "مجھے پرانی قبض کی شکایت ہے", "duration": "chronic",
             "age_group": "adult", "pregnancy": "na", "urine_color": "red", "bowel": "constipation", "body": "dry",
             "abdomen": "gas", "taste": "sour", "heart": "yes", "burning_urine": "no", "catarrh": "no", "phlegm": "none"}
