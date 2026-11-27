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
def api(db):
    _, key = ApiClient.create("android-test")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    return c


# the reference consultation of the CLI: chronic constipation, adult, muscular signs
REFERENCE = {"red_flags": ["none"], "complaint": "مجھے پرانی قبض کی شکایت ہے", "duration": "chronic",
             "age_group": "adult", "pregnancy": "na", "urine_color": "red", "bowel": "constipation", "body": "dry",
             "abdomen": "gas", "taste": "sour", "heart": "yes", "burning_urine": "no", "catarrh": "no", "phlegm": "none"}
