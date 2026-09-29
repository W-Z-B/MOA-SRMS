import pytest
from django.db import DatabaseError, transaction

from audit.models import AuditLog


@pytest.mark.django_db
def test_audit_log_is_insert_only(registrar):
    entry = AuditLog.objects.create(actor=registrar, action="test", entity="x.y", entity_id=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).update(action="tampered")
    with pytest.raises(DatabaseError), transaction.atomic():
        entry.delete()
    assert AuditLog.objects.get(pk=entry.pk).action == "test"
