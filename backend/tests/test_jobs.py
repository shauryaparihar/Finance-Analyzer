import threading
import time
import uuid

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from backend.core import repository as repo
from backend.core.models import AnalysisResult, AnalysisRun
from backend.ml.pipeline import ModuleOutcome
from backend.services import analysis_job
from backend.services.analysis_job import overall_status, run_analysis_job
from backend.services.jobs import JobRunner, SyncJobRunner

MODULES = ("categorization", "forecast", "anomaly", "summary")


# --- the bounded runner ---

def test_the_runner_never_exceeds_its_worker_limit():
    runner = JobRunner(workers=2)
    lock, state = threading.Lock(), {"now": 0, "max": 0}

    def job():
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1

    futures = [runner.submit(job) for _ in range(8)]
    for f in futures:
        f.result(timeout=5)
    runner.shutdown()
    assert state["max"] == 2


def test_a_crashing_job_does_not_stop_the_worker():
    runner = JobRunner(workers=1)
    done = threading.Event()

    def bad():
        raise RuntimeError("boom")

    runner.submit(bad).result(timeout=5)
    runner.submit(done.set).result(timeout=5)
    runner.shutdown()
    assert done.is_set()


def test_shutdown_cancels_queued_jobs_waits_for_the_running_one_and_refuses_new_work():
    runner = JobRunner(workers=1)
    started, release, ran = threading.Event(), threading.Event(), []

    def running():
        started.set()
        release.wait(5)
        ran.append("running")

    runner.submit(running)
    queued = runner.submit(lambda: ran.append("queued"))
    started.wait(5)
    threading.Timer(0.1, release.set).start()
    runner.shutdown()
    assert ran == ["running"] and queued.cancelled()
    assert runner.is_running is False
    with pytest.raises(RuntimeError):
        runner.submit(lambda: None)


def test_a_runner_needs_at_least_one_worker():
    with pytest.raises(ValueError):
        JobRunner(workers=0)


# --- status transitions ---

def _upload(db, email="u@example.com"):
    user = repo.get_user_by_email(db, email) or repo.create_user(db, email, "hash")
    return user, repo.create_upload(db, user.id, "f.csv", uuid.uuid4().hex * 2, 3, amount_convention="expenses_positive")


@pytest.mark.parametrize(
    "path",
    [["processing", "completed"], ["processing", "partial"], ["processing", "failed"], ["failed"]],
)
def test_valid_status_transitions(db, path):
    user, upload = _upload(db)
    for status in path:
        assert repo.update_upload_status(db, user.id, upload.id, status) is True
    db.refresh(upload)
    assert upload.status == path[-1]
    if path[-1] in ("completed", "partial", "failed"):
        assert upload.completed_at is not None


@pytest.mark.parametrize(
    "start,target",
    [("queued", "completed"), ("queued", "partial"), ("completed", "processing"), ("failed", "completed"), ("partial", "completed"), ("processing", "queued")],
)
def test_invalid_status_transitions_are_refused(db, start, target):
    user, upload = _upload(db)
    path = {"queued": [], "completed": ["processing", "completed"], "failed": ["failed"], "partial": ["processing", "partial"], "processing": ["processing"]}[start]
    for status in path:
        repo.update_upload_status(db, user.id, upload.id, status)
    with pytest.raises(repo.InvalidStatusTransition):
        repo.update_upload_status(db, user.id, upload.id, target)


def _run(status):
    return type("Run", (), {"status": status})()


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["completed"] * 4, "completed"),
        (["completed", "skipped", "skipped", "completed"], "completed"),  # skipped = not enough data, not a failure
        (["completed", "failed", "completed", "completed"], "partial"),
        (["failed", "failed", "failed", "failed"], "failed"),
        (["failed", "skipped", "skipped", "skipped"], "failed"),
    ],
)
def test_overall_status_from_module_runs(statuses, expected):
    assert overall_status([_run(s) for s in statuses]) == expected


# --- the analysis job (with controlled pipelines) ---

def _frame():
    return pd.DataFrame({"date": pd.date_range("2025-03-01", periods=4), "amount": [10.0, 20.0, 30.0, 40.0], "description": list("abcd")})


def _fake_pipeline(failed=(), skipped=(), preprocessing_fails=False, crash=False):
    def pipeline(df, categorizer, observer=None):
        if crash:
            raise RuntimeError("explode")
        if preprocessing_fails:
            return {"status": "failed", "modules": {}, "errors": ["Preprocessing failed"]}
        modules = {}
        for module in MODULES:
            observer.on_start(module)
            if module in failed:
                observer.on_finish(module, ModuleOutcome("failed", error_code=f"{module.upper()}_FAILED", error_message="step failed"), 5)
            elif module in skipped:
                observer.on_finish(module, ModuleOutcome("skipped", error_code="INSUFFICIENT_DATA", error_message="too little data"), 2)
            else:
                modules[module] = {"module": module}
                observer.on_finish(module, ModuleOutcome("completed", model_version=f"{module}-v1"), 7)
        return {"status": "completed", "modules": modules, "errors": [], "processed_df": df}

    return pipeline


@pytest.fixture
def job_env(test_engine, db):
    factory = sessionmaker(bind=test_engine)
    user, upload = _upload(db)
    repo.create_runs(db, user.id, upload.id)
    return factory, user, upload


def _go(job_env, monkeypatch, pipeline):
    factory, user, upload = job_env
    monkeypatch.setattr(analysis_job, "run_full_pipeline", pipeline)
    run_analysis_job(factory, user.id, upload.id, _frame(), categorizer=None, request_id="req-1234567")
    with factory() as session:
        return repo.get_upload(session, user.id, upload.id), repo.list_runs(session, user.id, upload.id)


def test_module_states_exist_as_pending_before_any_work_starts(job_env, db):
    _, user, upload = job_env
    runs = repo.list_runs(db, user.id, upload.id)
    assert [r.module for r in runs] == list(MODULES) and {r.status for r in runs} == {"pending"}
    assert upload.status == "queued"


def test_a_clean_run_completes_and_records_each_module(job_env, monkeypatch):
    upload, runs = _go(job_env, monkeypatch, _fake_pipeline())
    assert upload.status == "completed" and upload.error_summary is None and upload.completed_at is not None
    assert {r.module: (r.status, r.duration_ms, r.model_version) for r in runs}["forecast"] == ("completed", 7, "forecast-v1")
    assert all(r.started_at and r.finished_at for r in runs)


def test_one_failed_module_makes_the_upload_partial_and_keeps_the_other_results(job_env, monkeypatch, db):
    upload, runs = _go(job_env, monkeypatch, _fake_pipeline(failed=("anomaly",)))
    assert upload.status == "partial" and "anomaly" in upload.error_summary
    by_module = {r.module: r for r in runs}
    assert by_module["anomaly"].status == "failed" and by_module["anomaly"].error_code == "ANOMALY_FAILED"
    assert by_module["summary"].status == "completed"
    stored = {r.result_type for r in db.query(AnalysisResult).filter_by(upload_id=upload.id)}
    assert {"categorization", "forecast", "summary"} <= stored and "anomaly" not in stored


def test_skipped_modules_do_not_make_an_upload_partial(job_env, monkeypatch):
    upload, runs = _go(job_env, monkeypatch, _fake_pipeline(skipped=("forecast", "anomaly")))
    assert upload.status == "completed"
    assert {r.module: r.status for r in runs}["forecast"] == "skipped"


def test_every_module_failing_marks_the_upload_failed(job_env, monkeypatch):
    upload, _ = _go(job_env, monkeypatch, _fake_pipeline(failed=MODULES))
    assert upload.status == "failed"


def test_a_preprocessing_failure_fails_the_upload_and_closes_the_pending_runs(job_env, monkeypatch):
    upload, runs = _go(job_env, monkeypatch, _fake_pipeline(preprocessing_fails=True))
    assert upload.status == "failed"
    assert {r.status for r in runs} == {"skipped"} and {r.error_code for r in runs} == {"PREPROCESSING_FAILED"}


def test_an_unexpected_crash_fails_the_upload_without_leaking_the_error(job_env, monkeypatch):
    upload, runs = _go(job_env, monkeypatch, _fake_pipeline(crash=True))
    assert upload.status == "failed" and upload.error_summary == "Analysis failed."
    assert {r.error_code for r in runs} == {"JOB_CRASHED"} and "explode" not in str(upload.error_summary)


def test_deleting_an_upload_mid_analysis_is_handled_quietly(job_env, monkeypatch, db):
    factory, user, upload = job_env

    def deleting_pipeline(df, categorizer, observer=None):
        with factory() as session:
            repo.delete_upload(session, user.id, upload.id)
        return _fake_pipeline()(df, categorizer, observer=None)

    monkeypatch.setattr(analysis_job, "run_full_pipeline", deleting_pipeline)
    run_analysis_job(factory, user.id, upload.id, _frame(), categorizer=None)  # must not raise
    assert repo.get_upload(db, user.id, upload.id) is None


# --- restart / shutdown ---

def test_stale_jobs_are_failed_and_their_open_runs_are_closed(db):
    user, upload = _upload(db)
    repo.create_runs(db, user.id, upload.id)
    repo.update_upload_status(db, user.id, upload.id, "processing")
    repo.start_run(db, user.id, upload.id, "forecast")
    assert repo.fail_stale_uploads(db) == 1
    db.expire_all()
    runs = db.query(AnalysisRun).filter_by(upload_id=upload.id).all()
    assert {r.status for r in runs} == {"failed"} and {r.error_code for r in runs} == {"INTERRUPTED"}
    assert repo.get_upload(db, user.id, upload.id).status == "failed" and repo.has_active_upload(db, user.id) is False


def test_completed_work_is_not_touched_by_the_stale_sweep(db):
    user, upload = _upload(db)
    repo.update_upload_status(db, user.id, upload.id, "processing")
    repo.update_upload_status(db, user.id, upload.id, "completed")
    assert repo.fail_stale_uploads(db) == 0


def test_startup_clears_stale_jobs_creates_the_runner_and_shutdown_stops_it(test_engine, db, monkeypatch):
    import asyncio

    import backend.main as main

    factory = sessionmaker(bind=test_engine)
    user, upload = _upload(db)
    repo.create_runs(db, user.id, upload.id)
    repo.update_upload_status(db, user.id, upload.id, "processing")
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "load_categorizer", lambda: object())

    async def lifecycle():
        async with main.lifespan(main.app):
            runner = main.app.state.job_runner
            assert runner.is_running and runner.workers >= 1
            with factory() as session:
                assert repo.get_upload(session, user.id, upload.id).status == "failed"  # swept at startup
        return runner

    runner = asyncio.run(lifecycle())
    assert runner.is_running is False


def test_work_still_queued_when_the_app_shuts_down_is_recorded_as_cancelled(test_engine, db, monkeypatch):
    import asyncio

    import backend.main as main

    factory = sessionmaker(bind=test_engine)
    user = repo.create_user(db, "u@example.com", "hash")
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "load_categorizer", lambda: object())
    created = {}

    async def lifecycle():
        async with main.lifespan(main.app):
            # accepted while the app is running, but never started before shutdown
            created["upload"] = repo.create_upload(db, user.id, "f.csv", "a" * 64, 1)
            repo.create_runs(db, user.id, created["upload"].id)

    asyncio.run(lifecycle())
    db.expire_all()
    upload = repo.get_upload(db, user.id, created["upload"].id)
    assert upload.status == "failed" and "shut down" in upload.error_summary
    assert {r.error_code for r in repo.list_runs(db, user.id, upload.id)} == {"INTERRUPTED"}
    assert repo.has_active_upload(db, user.id) is False


def test_the_synchronous_test_runner_runs_jobs_immediately_and_survives_errors():
    hits = []
    runner = SyncJobRunner()
    runner.submit(hits.append, 1)
    runner.submit(lambda: 1 / 0)
    assert hits == [1]


# --- the duplicate lookup itself must be isolated per user (the API has a second guard; this checks the first) ---

def _finished(db, user, sha, convention="expenses_positive", status="completed"):
    upload = repo.create_upload(db, user.id, "f.csv", sha, 3, amount_convention=convention)
    repo.update_upload_status(db, user.id, upload.id, "processing")
    repo.update_upload_status(db, user.id, upload.id, status)
    return upload


def test_the_duplicate_lookup_never_returns_another_users_upload(db):
    owner = repo.create_user(db, "owner@example.com", "hash")
    other = repo.create_user(db, "other@example.com", "hash")
    mine = _finished(db, owner, "a" * 64)
    assert repo.find_reusable_upload(db, owner.id, "a" * 64, "expenses_positive").id == mine.id
    assert repo.find_reusable_upload(db, other.id, "a" * 64, "expenses_positive") is None


def test_the_duplicate_lookup_requires_the_same_file_convention_and_a_completed_upload(db):
    user = repo.create_user(db, "u@example.com", "hash")
    _finished(db, user, "b" * 64, status="failed")
    _finished(db, user, "c" * 64, convention="expenses_negative")
    assert repo.find_reusable_upload(db, user.id, "b" * 64, "expenses_positive") is None  # failed uploads are never reused
    assert repo.find_reusable_upload(db, user.id, "c" * 64, "expenses_positive") is None  # different convention
    assert repo.find_reusable_upload(db, user.id, "d" * 64, "expenses_negative") is None  # different file
    assert repo.find_reusable_upload(db, user.id, "c" * 64, "expenses_negative") is not None


def test_the_duplicate_lookup_returns_the_newest_match(db):
    user = repo.create_user(db, "u@example.com", "hash")
    _finished(db, user, "e" * 64)
    newest = _finished(db, user, "e" * 64)
    assert repo.find_reusable_upload(db, user.id, "e" * 64, "expenses_positive").id == newest.id
