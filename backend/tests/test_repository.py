import uuid
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.core import repository as repo
from backend.core.models import AnalysisResult, AnalysisRun, Budget, Transaction, Upload


def _user(db, email="a@example.com"):
    return repo.create_user(db, email, "hash")


def _upload(db, user, sha="a" * 64):
    return repo.create_upload(db, user.id, "file.csv", sha, 2)


def _frame():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "amount": [10.10, -2500.00],
            "category": ["Dining", "Uncategorized"],
            "description": ["Pizza", None],
        }
    )


def test_create_read_delete_upload(db):
    user = _user(db)
    upload = _upload(db, user)
    assert repo.get_upload(db, user.id, upload.id).original_filename == "file.csv"
    assert [u.id for u in repo.list_uploads(db, user.id)] == [upload.id]
    assert repo.delete_upload(db, user.id, upload.id) is True
    assert repo.get_upload(db, user.id, upload.id) is None


def test_other_users_cannot_read_or_delete_an_upload(db):
    owner, intruder = _user(db, "owner@example.com"), _user(db, "intruder@example.com")
    upload = _upload(db, owner)
    repo.store_transactions(db, owner.id, upload.id, _frame())

    assert repo.get_upload(db, intruder.id, upload.id) is None
    assert repo.list_uploads(db, intruder.id) == []
    assert repo.get_transactions(db, intruder.id, upload.id) == []
    assert repo.delete_upload(db, intruder.id, upload.id) is False
    with pytest.raises(LookupError):
        repo.store_transactions(db, intruder.id, upload.id, _frame())
    assert repo.get_upload(db, owner.id, upload.id) is not None


def test_delete_upload_cascades_to_dependent_rows(db):
    user = _user(db)
    upload = _upload(db, user)
    repo.store_transactions(db, user.id, upload.id, _frame())
    repo.upsert_analysis_result(db, user.id, upload.id, "summary", {"total": 1})
    db.add(AnalysisRun(upload_id=upload.id, module="summary", status="completed"))
    db.commit()

    assert repo.delete_upload(db, user.id, upload.id) is True
    for model in (Transaction, AnalysisResult, AnalysisRun):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_store_transactions_keeps_exact_money_and_nulls(db):
    user = _user(db)
    upload = _upload(db, user)
    assert repo.store_transactions(db, user.id, upload.id, _frame()) == 2
    first, second = repo.get_transactions(db, user.id, upload.id)
    assert first.amount == Decimal("10.10") and second.amount == Decimal("-2500.00")
    assert first.source_category == "Dining"
    assert second.source_category is None and second.description is None
    assert first.anomaly_review_status == "unreviewed"


def test_analysis_result_upsert_replaces_and_cleans_nan(db):
    user = _user(db)
    upload = _upload(db, user)
    repo.upsert_analysis_result(db, user.id, upload.id, "summary", {"value": float("nan")})
    assert repo.get_analysis_result(db, user.id, upload.id, "summary") == {"value": None}
    repo.upsert_analysis_result(db, user.id, upload.id, "summary", {"value": 2})
    assert repo.get_analysis_result(db, user.id, upload.id, "summary") == {"value": 2}
    assert db.scalar(select(func.count()).select_from(AnalysisResult)) == 1
    other = _user(db, "other@example.com")
    assert repo.get_analysis_result(db, other.id, upload.id, "summary") is None


def test_duplicate_budget_category_is_rejected_for_one_user(db):
    user = _user(db)
    db.add(Budget(user_id=user.id, category="Dining", monthly_limit=Decimal("100")))
    db.commit()
    db.add(Budget(user_id=user.id, category="Dining", monthly_limit=Decimal("200")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_budget_upsert_and_isolation_between_users(db):
    a, b = _user(db, "a@example.com"), _user(db, "b@example.com")
    repo.upsert_budget(db, a.id, "Dining", Decimal("100"))
    updated = repo.upsert_budget(db, a.id, "Dining", Decimal("150.505"))
    assert updated.monthly_limit == Decimal("150.51")
    repo.upsert_budget(db, b.id, "Dining", Decimal("10"))
    assert [x.monthly_limit for x in repo.list_budgets(db, a.id)] == [Decimal("150.51")]
    assert repo.delete_budget(db, b.id, "Dining") is True
    assert repo.delete_budget(db, b.id, "Dining") is False
    assert len(repo.list_budgets(db, a.id)) == 1


def test_non_positive_budget_limit_is_rejected(db):
    user = _user(db)
    with pytest.raises(IntegrityError):
        repo.upsert_budget(db, user.id, "Dining", Decimal("0"))


def test_unknown_upload_id_returns_nothing(db):
    user = _user(db)
    assert repo.get_upload(db, user.id, uuid.uuid4()) is None
    assert db.scalar(select(func.count()).select_from(Upload)) == 0
