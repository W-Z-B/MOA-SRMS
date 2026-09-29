import pytest
from django.core.exceptions import ImproperlyConfigured

from core import crypto


def test_encrypt_decrypt_round_trip():
    token = crypto.encrypt("987654321")
    assert token != b"987654321"
    assert crypto.decrypt(token) == "987654321"


def test_mask_shows_only_last_characters():
    assert crypto.mask("987654321").endswith("321") and "987" not in crypto.mask("987654321")
    assert crypto.mask(None) is None


def test_missing_key_is_a_configuration_error(settings):
    settings.FIELD_ENCRYPTION_KEY = ""
    crypto._fernet.cache_clear()
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")
    crypto._fernet.cache_clear()


@pytest.mark.django_db
def test_seed_is_idempotent(seeded):
    from django.core.management import call_command

    from academics.models import GradeBand, Term
    from programmes.models import Programme

    before = (Programme.objects.count(), GradeBand.objects.count(), Term.objects.count())
    call_command("seed", "--country", "GY", "--year", "2026", verbosity=0)
    assert (Programme.objects.count(), GradeBand.objects.count(), Term.objects.count()) == before
    assert Term.objects.filter(is_current=True).count() == 1
