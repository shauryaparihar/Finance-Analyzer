import uuid

from backend.core import repository as repo
from backend.core.models import AnalysisRun
from backend.services.ops_report import build_ops_report


def _finished_upload(db, user, status, runs, categorization=None, forecast=None):
    upload = repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 10)
    repo.update_upload_status(db, user.id, upload.id, "processing")
    repo.update_upload_status(db, user.id, upload.id, status)
    repo.create_runs(db, user.id, upload.id)
    for module, run_status, duration, version, code in runs:
        repo.finish_run(db, user.id, upload.id, module, run_status, duration, version, code)
    if categorization:
        repo.upsert_analysis_result(db, user.id, upload.id, "categorization", categorization)
    if forecast:
        repo.upsert_analysis_result(db, user.id, upload.id, "forecast", forecast)
    return upload


def test_the_report_answers_the_monitoring_questions_with_aggregates_only(db):
    user = repo.create_user(db, "ops@example.com", "hash")
    _finished_upload(
        db, user, "completed",
        [("categorization", "completed", 100, "tfidf-lr-x", None), ("forecast", "completed", 2000, "lag_random_forest", None),
         ("anomaly", "completed", 50, "deviation", None), ("summary", "completed", 10, None, None)],
        categorization={"model_version": "tfidf-lr-x", "rows": 100, "auto_categorized": 90, "needs_review": 10},
        forecast={"status": "completed", "method": "lag_random_forest"},
    )
    _finished_upload(
        db, user, "partial",
        [("categorization", "completed", 300, "tfidf-lr-x", None), ("forecast", "failed", 5, None, "FORECAST_FAILED"),
         ("anomaly", "skipped", 1, None, "INSUFFICIENT_DATA"), ("summary", "completed", 30, None, None)],
        categorization={"model_version": "tfidf-lr-x", "rows": 50, "auto_categorized": 40, "needs_review": 10},
        forecast={"status": "completed", "method": "seasonal_naive"},
    )
    _finished_upload(db, user, "failed", [("categorization", "failed", 7, None, "CATEGORIZATION_FAILED")])

    report = build_ops_report(db)
    assert report["uploads_by_status"] == {"completed": 1, "partial": 1, "failed": 1}
    assert {(f["module"], f["error_code"], f["count"]) for f in report["failed_modules"]} == {
        ("forecast", "FORECAST_FAILED", 1), ("categorization", "CATEGORIZATION_FAILED", 1)}
    assert report["skipped_modules"] == [{"module": "anomaly", "reason_code": "INSUFFICIENT_DATA", "count": 1}]
    assert report["module_duration_ms"]["categorization"]["runs"] == 2 and report["module_duration_ms"]["categorization"]["avg_ms"] == 200.0
    assert {"module": "categorization", "model_version": "tfidf-lr-x", "runs": 2} in report["model_versions"]
    assert report["categorization"] == {"rows": 150, "auto_categorized": 130, "sent_to_review": 20, "auto_rate": round(130 / 150, 4)}
    assert report["forecast_method_selected"] == {"lag_random_forest": 1, "seasonal_naive": 1}


def test_the_report_works_on_an_empty_database_and_contains_no_transaction_text(db):
    report = build_ops_report(db)
    assert report["uploads_by_status"] == {} and report["categorization"]["auto_rate"] is None
    assert "description" not in str(report).lower()
    assert db.query(AnalysisRun).count() == 0
