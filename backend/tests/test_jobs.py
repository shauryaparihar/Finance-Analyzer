import threading
import time
import uuid

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.core import repository as repo
from backend.core.models import AnalysisResult, AnalysisRun, Transaction, Upload, UploadInput
from backend.ml.pipeline import ModuleOutcome
from backend.services import analysis_job
from backend.services.analysis_job import overall_status, run_analysis_job
from backend.services.job_input import decode_input, encode_input
from backend.services.jobs import InlineJobRunner, JobRunner

MODULES = ("categorization", "forecast", "anomaly", "summary")


# --- helpers ---

def _frame(n=4):
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-03-01", periods=n),
            "amount": [10.0 * (i + 1) for i in range(n)],
            "description": [f"item {i}" for i in range(n)],
        }
    )


def _user(db, name="u"):
    return repo.get_user_by_email(db, f"{name}@example.com") or repo.create_user(db, f"{name}@example.com", "hash")


def _enqueue(db, user, df=None, sha=None):
    return repo.enqueue_upload(
        db, user.id, "f.csv", sha or uuid.uuid4().hex * 2, 4, "expenses_positive", encode_input(df if df is not None else _frame())
    )


def _status(factory, upload_id):
    with factory() as session:
        return session.get(Upload, upload_id).status


def _wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _complete(factory, worker_id, user_id, upload_id, attempts, request_id):
    with factory() as session:
        repo.update_upload_status(session, user_id, upload_id, "completed", worker_id=worker_id)


def _runner(factory, process=None, instance_id="inst", workers=2, ready=lambda: True, **kw):
    kw.setdefault("poll_seconds", 0.02)
    kw.setdefault("heartbeat_seconds", 0.05)
    kw.setdefault("stale_after_seconds", 60)
    return JobRunner(factory, process or (lambda factory, **claim: _complete(factory, **claim)), ready, instance_id, workers=workers, **kw)


@pytest.fixture
def factory(test_engine):
    return sessionmaker(bind=test_engine)


# --- the queue and its workers ---

def test_the_runner_never_runs_more_jobs_at_once_than_it_has_workers(db, factory):
    lock, state = threading.Lock(), {"now": 0, "max": 0}

    def process(factory_, *, worker_id, user_id, upload_id, attempts, request_id):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.08)
        with lock:
            state["now"] -= 1
        _complete(factory_, worker_id, user_id, upload_id, attempts, request_id)

    uploads = [_enqueue(db, _user(db, f"user{i}")) for i in range(6)]
    runner = _runner(factory, process, workers=2)
    runner.start()
    assert _wait_until(lambda: all(_status(factory, u.id) == "completed" for u in uploads))
    runner.shutdown()
    assert state["max"] == 2


def test_jobs_are_taken_oldest_first(db, factory):
    order, lock = [], threading.Lock()

    def process(factory_, *, worker_id, user_id, upload_id, attempts, request_id):
        with lock:
            order.append(upload_id)
        _complete(factory_, worker_id, user_id, upload_id, attempts, request_id)

    uploads = [_enqueue(db, _user(db, f"user{i}")) for i in range(4)]
    runner = _runner(factory, process, workers=1)
    assert runner.drain() == 4
    assert order == [u.id for u in uploads]


def test_a_crashing_job_does_not_stop_the_worker_and_the_next_job_runs(db, factory):
    done = []

    def process(factory_, *, worker_id, user_id, upload_id, attempts, request_id):
        if not done and attempts == 1 and upload_id == first.id:
            done.append("crash")
            raise RuntimeError("boom")
        _complete(factory_, worker_id, user_id, upload_id, attempts, request_id)

    first = _enqueue(db, _user(db, "a"))
    second = _enqueue(db, _user(db, "b"))
    runner = _runner(factory, process, workers=1)
    runner.start()
    assert _wait_until(lambda: _status(factory, second.id) == "completed")
    runner.shutdown()
    assert done == ["crash"]


def test_the_runner_leaves_work_queued_while_it_is_not_ready_and_runs_it_once_ready(db, factory):
    ready = {"ok": False}
    upload = _enqueue(db, _user(db))
    runner = _runner(factory, ready=lambda: ready["ok"], workers=1)
    runner.start()
    time.sleep(0.2)
    assert _status(factory, upload.id) == "queued"  # for example: the categorizer failed to load
    ready["ok"] = True
    assert _wait_until(lambda: _status(factory, upload.id) == "completed")
    runner.shutdown()


def test_shutdown_waits_for_the_running_job_and_leaves_queued_jobs_queued(db, factory):
    started, release = threading.Event(), threading.Event()

    def process(factory_, *, worker_id, user_id, upload_id, attempts, request_id):
        started.set()
        release.wait(5)
        _complete(factory_, worker_id, user_id, upload_id, attempts, request_id)

    running = _enqueue(db, _user(db, "a"))
    waiting = _enqueue(db, _user(db, "b"))
    runner = _runner(factory, process, workers=1)
    runner.start()
    assert started.wait(5)
    threading.Timer(0.15, release.set).start()
    runner.shutdown()
    assert runner.is_running is False
    assert _status(factory, running.id) == "completed"
    assert _status(factory, waiting.id) == "queued"  # durable: the next worker will take it, it is not lost


def test_a_queued_job_survives_a_restart_and_is_processed_by_the_new_process(db, factory):
    upload = _enqueue(db, _user(db))
    first_process = _runner(factory, instance_id="before-restart")
    first_process.shutdown()  # the old process goes away without ever running it
    assert _status(factory, upload.id) == "queued"
    second_process = _runner(factory, instance_id="after-restart")
    second_process.start()
    assert _wait_until(lambda: _status(factory, upload.id) == "completed")
    second_process.shutdown()
    with factory() as session:
        assert session.get(Upload, upload.id).claimed_by.startswith("after-restart")


def test_a_runner_needs_at_least_one_worker(factory):
    with pytest.raises(ValueError):
        JobRunner(factory, lambda *a, **k: None, lambda: True, "x", workers=0)


def test_the_heartbeat_keeps_refreshing_while_a_job_runs(db, factory):
    seen = []

    def process(factory_, *, worker_id, user_id, upload_id, attempts, request_id):
        with factory_() as session:
            seen.append(session.get(Upload, upload_id).heartbeat_at)
        time.sleep(0.4)
        with factory_() as session:
            seen.append(session.get(Upload, upload_id).heartbeat_at)
        _complete(factory_, worker_id, user_id, upload_id, attempts, request_id)

    _enqueue(db, _user(db))
    assert _runner(factory, process, workers=1, heartbeat_seconds=0.05).drain() == 1
    assert seen[1] > seen[0]


# --- several instances sharing one queue ---

def test_two_instances_share_the_queue_without_taking_the_same_job(db, factory):
    lock, runs, spans = threading.Lock(), [], []

    def process(factory_, *, worker_id, user_id, upload_id, attempts, request_id):
        began = time.monotonic()
        time.sleep(0.15)
        with lock:
            runs.append(upload_id)
            spans.append((worker_id.split("/")[0], began, time.monotonic()))
        _complete(factory_, worker_id, user_id, upload_id, attempts, request_id)

    uploads = [_enqueue(db, _user(db, f"user{i}")) for i in range(6)]
    a = _runner(factory, process, instance_id="instance-A", workers=1)
    b = _runner(factory, process, instance_id="instance-B", workers=1)
    a.start()
    b.start()
    assert _wait_until(lambda: all(_status(factory, u.id) == "completed" for u in uploads))
    a.shutdown()
    b.shutdown()
    assert sorted(runs) == sorted(u.id for u in uploads)  # every job ran exactly once
    with factory() as session:
        owners = {session.get(Upload, u.id).claimed_by.split("/")[0] for u in uploads}
    assert owners == {"instance-A", "instance-B"}  # both instances did real work
    a_spans = [s for s in spans if s[0] == "instance-A"]
    b_spans = [s for s in spans if s[0] == "instance-B"]
    assert any(x[1] < y[2] and y[1] < x[2] for x in a_spans for y in b_spans)  # and they ran at the same time


def test_claiming_is_exclusive_under_contention(db, factory):
    for i in range(10):
        _enqueue(db, _user(db, f"user{i}"))
    claimed, lock = [], threading.Lock()

    def worker(name):
        while True:
            with factory() as session:
                job = repo.claim_next_job(session, name)
                if job is None:
                    return
                with lock:
                    claimed.append(job.id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 10 and len(set(claimed)) == 10


# --- recovery ---

def _kill_worker(db, upload, minutes_ago=5, attempts=1, worker="dead-instance/w0"):
    """Make an upload look like its worker died `minutes_ago` minutes ago."""
    db.execute(
        update(Upload)
        .where(Upload.id == upload.id)
        .values(status="processing", claimed_by=worker, attempts=attempts, heartbeat_at=func.now() - text(f"interval '{minutes_ago} minutes'"))
    )
    db.commit()
    db.expire_all()


def test_a_job_whose_worker_died_is_requeued_and_completed_by_another_worker(db, factory):
    upload = _enqueue(db, _user(db))
    _kill_worker(db, upload)
    runner = _runner(factory, instance_id="survivor", workers=1)
    assert runner.reap_if_due(force=True) == {"requeued": 1, "failed": 0}
    db.expire_all()
    assert db.get(Upload, upload.id).status == "queued" and db.get(Upload, upload.id).claimed_by is None
    assert runner.drain() == 1
    db.expire_all()
    done = db.get(Upload, upload.id)
    assert done.status == "completed" and done.attempts == 2 and done.claimed_by.startswith("survivor")


def test_a_running_job_with_a_fresh_heartbeat_is_never_touched_by_another_instance(db, factory):
    upload = _enqueue(db, _user(db))
    _kill_worker(db, upload, minutes_ago=0, worker="instance-A/w0")  # alive: heartbeat is current
    other_instance = _runner(factory, instance_id="instance-B", workers=1)
    for _ in range(3):
        assert other_instance.reap_if_due(force=True) == {"requeued": 0, "failed": 0}
    other_instance.start()  # a second instance starting up must not disturb it either
    time.sleep(0.2)
    other_instance.shutdown()
    db.expire_all()
    job = db.get(Upload, upload.id)
    assert job.status == "processing" and job.claimed_by == "instance-A/w0" and job.attempts == 1


def test_a_job_that_keeps_getting_interrupted_is_eventually_failed_not_retried_forever(db, factory):
    upload = _enqueue(db, _user(db))
    _kill_worker(db, upload, attempts=2)  # already tried twice (the maximum)
    assert _runner(factory, workers=1).reap_if_due(force=True) == {"requeued": 0, "failed": 1}
    db.expire_all()
    job = db.get(Upload, upload.id)
    assert job.status == "failed" and "interrupted repeatedly" in job.error_summary
    assert {r.error_code for r in repo.list_runs(db, upload.user_id, upload.id)} == {"INTERRUPTED"}
    assert repo.get_job_input(db, upload.id) is None and repo.has_active_upload(db, upload.user_id) is False


def test_a_retry_clears_a_dead_attempts_partial_output_instead_of_duplicating_it(db, factory, monkeypatch):
    user = _user(db)
    upload = _enqueue(db, user)
    # attempt 1 stored its transactions and a result, then its worker died
    repo.update_upload_status(db, user.id, upload.id, "processing")
    repo.store_transactions(db, user.id, upload.id, _frame().assign(category=None))
    repo.upsert_analysis_result(db, user.id, upload.id, "summary", {"stale": True})
    _kill_worker(db, upload)
    runner = _runner(factory, workers=1)
    runner.reap_if_due(force=True)
    monkeypatch.setattr(analysis_job, "run_full_pipeline", _fake_pipeline())
    runner.process = analysis_job.make_processor(lambda: None)
    assert runner.drain() == 1
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.upload_id == upload.id)) == 4  # not 8
    assert db.scalar(select(func.count()).select_from(AnalysisResult).where(AnalysisResult.upload_id == upload.id, AnalysisResult.result_type == "summary")) == 1
    assert repo.get_analysis_result(db, user.id, upload.id, "summary") != {"stale": True}
    assert db.get(Upload, upload.id).status == "completed"


def test_a_worker_that_lost_its_claim_cannot_overwrite_the_newer_attempt(db, factory, monkeypatch):
    user = _user(db)
    upload = _enqueue(db, user)
    claimed = {}

    def pipeline_where_the_claim_is_lost(df, categorizer, observer=None):
        # while worker w1 is busy, its heartbeat lapses, the job is requeued and worker w2 claims it
        with factory() as session:
            _kill_worker(session, upload, worker="w1")
            repo.reap_orphaned_jobs(session, stale_after_seconds=60, max_attempts=3)
        with factory() as session:
            claimed["by"] = repo.claim_next_job(session, "w2").claimed_by
        return {"status": "completed", "modules": {"summary": {"zombie": True}}, "errors": [], "processed_df": df}

    with factory() as session:
        job = repo.claim_next_job(session, "w1")
    monkeypatch.setattr(analysis_job, "run_full_pipeline", pipeline_where_the_claim_is_lost)
    run_analysis_job(factory, user.id, upload.id, None, "w1", attempts=job.attempts)  # must not raise
    db.expire_all()
    current = db.get(Upload, upload.id)
    assert claimed["by"] == "w2" and current.claimed_by == "w2" and current.status == "processing"  # w2 still owns it
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.upload_id == upload.id)) == 0
    assert repo.get_analysis_result(db, user.id, upload.id, "summary") is None  # the zombie wrote nothing


def test_only_the_claiming_worker_may_change_the_status(db):
    user = _user(db)
    upload = _enqueue(db, user)
    job = repo.claim_next_job(db, "owner/w0")
    with pytest.raises(repo.ClaimLost):
        repo.update_upload_status(db, user.id, job.id, "completed", worker_id="someone-else/w1")
    assert repo.update_upload_status(db, user.id, job.id, "completed", worker_id="owner/w0") is True
    assert upload.id == job.id


# --- the stored input ---

def test_the_input_round_trips_with_text_kept_as_text_and_extra_columns_dropped():
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp("2025-01-05"), pd.Timestamp("2025-02-10 13:30:00")],  # a date and a date with a time
            "amount": [12.5, -2000.0],
            "description": ["00123", None],  # a numeric-looking description must not turn into a number
            "category": [None, "Groceries"],
            "account_number": ["999-SECRET", "999-SECRET"],  # not needed by the analysis: not stored
        }
    )
    out = decode_input(encode_input(df))
    assert list(out.columns) == ["date", "amount", "description", "category"]
    assert out["description"][0] == "00123" and pd.isna(out["description"][1]) and pd.isna(out["category"][0])
    assert list(out["amount"]) == [12.5, -2000.0] and out["date"].tolist() == df["date"].tolist()
    assert out["amount"].dtype == np.float64 and "SECRET" not in encode_input(df).decode("latin-1")


def test_the_input_is_deleted_when_the_job_finishes_and_removed_with_the_upload(db):
    user = _user(db)
    done = _enqueue(db, user)
    repo.claim_next_job(db, "w")
    assert repo.get_job_input(db, done.id) is not None
    repo.update_upload_status(db, user.id, done.id, "completed", worker_id="w")
    assert repo.get_job_input(db, done.id) is None

    other = _user(db, "other")
    pending = _enqueue(db, other)
    assert repo.delete_upload(db, other.id, pending.id) is True
    assert db.scalar(select(func.count()).select_from(UploadInput)) == 0


def test_queuing_is_all_or_nothing_when_the_user_already_has_an_active_job(db):
    user = _user(db)
    _enqueue(db, user)
    with pytest.raises(IntegrityError):
        _enqueue(db, user)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Upload)) == 1
    assert db.scalar(select(func.count()).select_from(UploadInput)) == 1
    assert db.scalar(select(func.count()).select_from(AnalysisRun)) == len(MODULES)  # no orphaned rows from the failed attempt


def test_a_job_whose_input_has_disappeared_fails_cleanly(db, factory):
    user = _user(db)
    upload = _enqueue(db, user)
    db.execute(text("DELETE FROM upload_inputs"))
    db.commit()
    runner = _runner(factory, workers=1)
    runner.process = analysis_job.make_processor(lambda: None)
    assert runner.drain() == 1
    db.expire_all()
    assert db.get(Upload, upload.id).status == "failed"
    assert {r.error_code for r in repo.list_runs(db, user.id, upload.id)} == {"INPUT_MISSING"}


# --- status rules ---

@pytest.mark.parametrize("path", [["processing", "completed"], ["processing", "partial"], ["processing", "failed"], ["failed"]])
def test_valid_status_transitions(db, path):
    user = _user(db)
    upload = _enqueue(db, user)
    for status in path:
        assert repo.update_upload_status(db, user.id, upload.id, status) is True
    db.refresh(upload)
    assert upload.status == path[-1] and upload.completed_at is not None if path[-1] != "processing" else True


@pytest.mark.parametrize(
    "start,target",
    [("queued", "completed"), ("queued", "partial"), ("completed", "processing"), ("failed", "completed"), ("partial", "completed"), ("processing", "queued")],
)
def test_invalid_status_transitions_are_refused(db, start, target):
    user = _user(db)
    upload = _enqueue(db, user)
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
        (["completed", "skipped", "skipped", "completed"], "completed"),
        (["completed", "failed", "completed", "completed"], "partial"),
        (["failed", "failed", "failed", "failed"], "failed"),
        (["failed", "skipped", "skipped", "skipped"], "failed"),
    ],
)
def test_overall_status_from_module_runs(statuses, expected):
    assert overall_status([_run(s) for s in statuses]) == expected


# --- the analysis job itself, with controlled pipelines ---

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
        return {"status": "completed", "modules": modules, "errors": [], "processed_df": df.assign(category=None)}

    return pipeline


@pytest.fixture
def claimed(factory, db):
    user = _user(db)
    upload = _enqueue(db, user)
    with factory() as session:
        job = repo.claim_next_job(session, "w1")
    return factory, user, upload, job


def _go(claimed, monkeypatch, pipeline):
    factory, user, upload, job = claimed
    monkeypatch.setattr(analysis_job, "run_full_pipeline", pipeline)
    run_analysis_job(factory, user.id, upload.id, None, "w1", attempts=job.attempts, request_id="req-1234567")
    with factory() as session:
        return repo.get_upload(session, user.id, upload.id), repo.list_runs(session, user.id, upload.id)


def test_module_states_exist_as_pending_before_any_work_starts(db):
    user = _user(db)
    upload = _enqueue(db, user)
    runs = repo.list_runs(db, user.id, upload.id)
    assert [r.module for r in runs] == list(MODULES) and {r.status for r in runs} == {"pending"}
    assert upload.status == "queued" and upload.attempts == 0


def test_a_clean_run_completes_records_each_module_and_deletes_the_input(claimed, monkeypatch, db):
    upload, runs = _go(claimed, monkeypatch, _fake_pipeline())
    assert upload.status == "completed" and upload.error_summary is None and upload.completed_at is not None
    assert {r.module: (r.status, r.duration_ms, r.model_version) for r in runs}["forecast"] == ("completed", 7, "forecast-v1")
    assert all(r.started_at and r.finished_at for r in runs)
    assert repo.get_job_input(db, upload.id) is None


def test_one_failed_module_makes_the_upload_partial_and_keeps_the_other_results(claimed, monkeypatch, db):
    upload, runs = _go(claimed, monkeypatch, _fake_pipeline(failed=("anomaly",)))
    assert upload.status == "partial" and "anomaly" in upload.error_summary
    by_module = {r.module: r for r in runs}
    assert by_module["anomaly"].status == "failed" and by_module["anomaly"].error_code == "ANOMALY_FAILED"
    assert by_module["summary"].status == "completed"
    stored = {r.result_type for r in db.query(AnalysisResult).filter_by(upload_id=upload.id)}
    assert {"categorization", "forecast", "summary"} <= stored and "anomaly" not in stored


def test_skipped_modules_do_not_make_an_upload_partial(claimed, monkeypatch):
    upload, runs = _go(claimed, monkeypatch, _fake_pipeline(skipped=("forecast", "anomaly")))
    assert upload.status == "completed" and {r.module: r.status for r in runs}["forecast"] == "skipped"


def test_every_module_failing_marks_the_upload_failed(claimed, monkeypatch):
    upload, _ = _go(claimed, monkeypatch, _fake_pipeline(failed=MODULES))
    assert upload.status == "failed"


def test_a_preprocessing_failure_fails_the_upload_and_closes_the_pending_runs(claimed, monkeypatch):
    upload, runs = _go(claimed, monkeypatch, _fake_pipeline(preprocessing_fails=True))
    assert upload.status == "failed"
    assert {r.status for r in runs} == {"skipped"} and {r.error_code for r in runs} == {"PREPROCESSING_FAILED"}


def test_an_unexpected_crash_fails_the_upload_without_leaking_the_error(claimed, monkeypatch):
    upload, runs = _go(claimed, monkeypatch, _fake_pipeline(crash=True))
    assert upload.status == "failed" and upload.error_summary == "Analysis failed."
    assert {r.error_code for r in runs} == {"JOB_CRASHED"} and "explode" not in str(upload.error_summary)


def test_deleting_an_upload_mid_analysis_is_handled_quietly(claimed, monkeypatch, db):
    factory, user, upload, job = claimed

    def deleting_pipeline(df, categorizer, observer=None):
        with factory() as session:
            repo.delete_upload(session, user.id, upload.id)
        return _fake_pipeline()(df, categorizer, observer=None)

    monkeypatch.setattr(analysis_job, "run_full_pipeline", deleting_pipeline)
    run_analysis_job(factory, user.id, upload.id, None, "w1", attempts=1)  # must not raise
    assert repo.get_upload(db, user.id, upload.id) is None


# --- application lifecycle ---

def test_startup_starts_workers_that_run_queued_work_and_shutdown_stops_them(test_engine, db, monkeypatch):
    import asyncio

    import backend.main as main
    from backend.services import analysis_job as aj

    factory = sessionmaker(bind=test_engine)
    user = _user(db)
    upload = _enqueue(db, user)  # queued before the app starts: it must still be picked up
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "load_categorizer", lambda: object())
    monkeypatch.setattr(aj, "run_full_pipeline", _fake_pipeline())

    async def lifecycle():
        async with main.lifespan(main.app):
            runner = main.app.state.job_runner
            assert runner.is_running and runner.workers >= 1
            assert await asyncio.to_thread(_wait_until, lambda: _status(factory, upload.id) == "completed")
        return runner

    runner = asyncio.run(lifecycle())
    assert runner.is_running is False


def test_work_still_queued_when_the_app_shuts_down_stays_queued(test_engine, db, monkeypatch):
    import asyncio

    import backend.main as main

    factory = sessionmaker(bind=test_engine)
    user = _user(db)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "load_categorizer", lambda: None)  # model unavailable: workers will not claim anything
    from backend.core.models import Upload as U

    async def lifecycle():
        async with main.lifespan(main.app):
            main.app.state.queued = _enqueue(db, user).id

    asyncio.run(lifecycle())
    db.expire_all()
    assert db.get(U, main.app.state.queued).status == "queued"  # durable: nothing cancelled or failed it


def test_the_inline_test_runner_runs_queued_jobs_when_woken(db, factory):
    upload = _enqueue(db, _user(db))
    runner = InlineJobRunner(factory, lambda factory_, **claim: _complete(factory_, **claim), lambda: True, "t")
    runner.wake()
    assert _status(factory, upload.id) == "completed"


# --- the write phase is one atomic, locked transaction ---

def test_saving_results_is_all_or_nothing(claimed, monkeypatch, db):
    factory, user, upload, job = claimed
    calls = {"n": 0}
    real = repo.upsert_analysis_result

    def fail_on_second_result(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("database hiccup while saving")
        return real(*args, **kwargs)

    monkeypatch.setattr(repo, "upsert_analysis_result", fail_on_second_result)
    final, _ = _go(claimed, monkeypatch, _fake_pipeline())
    db.expire_all()
    assert calls["n"] == 2
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.upload_id == upload.id)) == 0
    assert db.scalar(select(func.count()).select_from(AnalysisResult).where(AnalysisResult.upload_id == upload.id)) == 0
    assert final.status == "failed"  # recorded as a failure; no half-written results are left behind


def test_a_reaper_cannot_take_a_job_while_its_owner_is_saving_results(db, factory):
    user = _user(db)
    upload = _enqueue(db, user)
    with factory() as session:
        repo.claim_next_job(session, "w1")
    _kill_worker(db, upload, worker="w1")  # w1 has been silent for minutes, but it is still the owner
    locked, release = threading.Event(), threading.Event()
    outcome = {}

    def owner_saves_results():
        with factory() as session:
            repo.lock_claim(session, user.id, upload.id, "w1")  # the lock is held from here until commit
            locked.set()
            release.wait(5)
            repo.update_upload_status(session, user.id, upload.id, "completed", worker_id="w1")

    thread = threading.Thread(target=owner_saves_results)
    thread.start()
    assert locked.wait(5)
    began = time.monotonic()
    with factory() as session:
        outcome["reaper"] = repo.reap_orphaned_jobs(session, stale_after_seconds=60, max_attempts=3)
    outcome["waited"] = time.monotonic() - began
    release.set()
    thread.join()
    db.expire_all()
    assert outcome["reaper"] == {"requeued": 0, "failed": 0}  # the locked row was skipped, not taken
    assert outcome["waited"] < 1.0  # ... and the reaper did not sit waiting for the lock
    job = db.get(Upload, upload.id)
    assert job.status == "completed" and job.attempts == 1  # the owner finished its own job exactly once


def test_the_heartbeat_does_not_hang_behind_the_save_lock(db, factory):
    user = _user(db)
    upload = _enqueue(db, user)
    with factory() as session:
        repo.claim_next_job(session, "w1")
    holder = factory()
    repo.lock_claim(holder, user.id, upload.id, "w1")
    began = time.monotonic()
    with factory() as session:
        alive = repo.beat(session, upload.id, "w1")
    holder.rollback()
    holder.close()
    assert alive is True and time.monotonic() - began < 3.0  # skipped quickly instead of waiting for the lock


def test_a_lost_claim_leaves_the_input_for_the_new_owner(db, factory, monkeypatch):
    user = _user(db)
    upload = _enqueue(db, user)
    with factory() as session:
        job = repo.claim_next_job(session, "w1")

    def claim_stolen(df, categorizer, observer=None):
        with factory() as session:
            _kill_worker(session, upload, worker="w1")
            repo.reap_orphaned_jobs(session, 60, 3)
            repo.claim_next_job(session, "w2")
        return _fake_pipeline()(df, categorizer, observer=None)

    monkeypatch.setattr(analysis_job, "run_full_pipeline", claim_stolen)
    run_analysis_job(factory, user.id, upload.id, None, "w1", attempts=job.attempts)
    assert repo.get_job_input(db, upload.id) is not None  # w2 still needs it; the stale worker must not delete it


# --- the stored input never outlives its job ---

@pytest.mark.parametrize(
    "scenario,expected_status",
    [
        ("completed", "completed"),
        ("partial", "partial"),
        ("all_failed", "failed"),
        ("preprocessing_failed", "failed"),
        ("crash", "failed"),
        ("input_missing", "failed"),
    ],
)
def test_the_stored_input_is_deleted_however_the_job_ends(claimed, monkeypatch, db, scenario, expected_status):
    factory, user, upload, job = claimed
    pipelines = {
        "completed": _fake_pipeline(),
        "partial": _fake_pipeline(failed=("anomaly",)),
        "all_failed": _fake_pipeline(failed=MODULES),
        "preprocessing_failed": _fake_pipeline(preprocessing_fails=True),
        "crash": _fake_pipeline(crash=True),
        "input_missing": _fake_pipeline(),
    }
    if scenario == "input_missing":
        db.execute(text("DELETE FROM upload_inputs"))
        db.commit()
    final, _ = _go(claimed, monkeypatch, pipelines[scenario])
    assert final.status == expected_status
    assert repo.get_job_input(db, upload.id) is None
    assert db.scalar(select(func.count()).select_from(UploadInput).where(UploadInput.upload_id == upload.id)) == 0


def test_the_real_job_holds_the_lock_while_saving_so_a_reaper_cannot_steal_it_mid_write(db, factory, monkeypatch):
    user = _user(db)
    upload = _enqueue(db, user)
    with factory() as session:
        job = repo.claim_next_job(session, "w1")
    _kill_worker(db, upload, worker="w1")  # silent for minutes: a reaper would normally take this job
    seen = {}
    real = repo.upsert_analysis_result

    def spy(*args, **kwargs):
        if "reaper" not in seen:  # first save call: the job is in the middle of its write phase
            began = time.monotonic()
            with factory() as other:
                seen["reaper"] = repo.reap_orphaned_jobs(other, stale_after_seconds=60, max_attempts=3)
            seen["waited"] = time.monotonic() - began
        return real(*args, **kwargs)

    monkeypatch.setattr(repo, "upsert_analysis_result", spy)
    monkeypatch.setattr(analysis_job, "run_full_pipeline", _fake_pipeline())
    run_analysis_job(factory, user.id, upload.id, None, "w1", attempts=job.attempts)
    db.expire_all()
    assert seen["reaper"] == {"requeued": 0, "failed": 0} and seen["waited"] < 1.0
    assert db.get(Upload, upload.id).status == "completed" and db.get(Upload, upload.id).attempts == 1
