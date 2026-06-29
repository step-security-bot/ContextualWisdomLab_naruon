from db.models import Email


def test_email_date_has_index():
    assert Email.__table__.c.date.index is True
