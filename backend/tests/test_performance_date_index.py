from sqlalchemy import inspect

from db.models import Attachment, Email


def test_email_date_has_index():
    assert Email.__table__.c.date.index is True


def test_large_embedding_columns_are_deferred_by_default():
    assert inspect(Email).attrs.embedding.deferred is True
    assert inspect(Attachment).attrs.embedding.deferred is True
