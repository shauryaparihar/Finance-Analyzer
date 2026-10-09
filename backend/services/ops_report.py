"""
Operational report from the database: how analyses are going. Aggregates only, never transaction text.

    python -m backend.services.ops_report

Answers: how many jobs completed / partially completed / failed; which module failed and why; how long each
module takes; which model version produced predictions; how many rows were categorized automatically versus
sent to review; and whether the baseline or the machine-learning forecast was selected.
"""
import json
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from backend.core.models import AnalysisResult, AnalysisRun, Upload


def build_ops_report(db: Session) -> dict[str, Any]:
    jobs = dict(db.execute(select(Upload.status, func.count()).group_by(Upload.status)).all())

    failures = [
        {"module": module, "error_code": code, "count": count}
        for module, code, count in db.execute(
            select(AnalysisRun.module, AnalysisRun.error_code, func.count())
            .where(AnalysisRun.status == "failed")
            .group_by(AnalysisRun.module, AnalysisRun.error_code)
            .order_by(func.count().desc())
        )
    ]
    skipped = [
        {"module": module, "reason_code": code, "count": count}
        for module, code, count in db.execute(
            select(AnalysisRun.module, AnalysisRun.error_code, func.count())
            .where(AnalysisRun.status == "skipped")
            .group_by(AnalysisRun.module, AnalysisRun.error_code)
        )
    ]
    durations = {
        module: {"runs": runs, "avg_ms": round(float(avg), 1), "p95_ms": round(float(p95), 1)}
        for module, runs, avg, p95 in db.execute(
            select(
                AnalysisRun.module,
                func.count(),
                func.avg(AnalysisRun.duration_ms),
                func.percentile_cont(0.95).within_group(AnalysisRun.duration_ms),
            )
            .where(AnalysisRun.status == "completed", AnalysisRun.duration_ms.is_not(None))
            .group_by(AnalysisRun.module)
        )
    }
    versions = [
        {"module": module, "model_version": version, "runs": count}
        for module, version, count in db.execute(
            select(AnalysisRun.module, AnalysisRun.model_version, func.count())
            .where(AnalysisRun.status == "completed", AnalysisRun.model_version.is_not(None))
            .group_by(AnalysisRun.module, AnalysisRun.model_version)
            .order_by(AnalysisRun.module)
        )
    ]

    cat = AnalysisResult.payload
    rows, auto, review = db.execute(
        select(
            func.coalesce(func.sum(cat["rows"].astext.cast(Integer)), 0),
            func.coalesce(func.sum(cat["auto_categorized"].astext.cast(Integer)), 0),
            func.coalesce(func.sum(cat["needs_review"].astext.cast(Integer)), 0),
        ).where(AnalysisResult.result_type == "categorization")
    ).one()
    method = cat["method"].astext.label("method")  # one labelled expression, so SELECT and GROUP BY match
    methods = dict(
        db.execute(
            select(method, func.count())
            .where(AnalysisResult.result_type == "forecast", cat["status"].astext == "completed")
            .group_by(method)
        ).all()
    )
    return {
        "uploads_by_status": jobs,
        "failed_modules": failures,
        "skipped_modules": skipped,
        "module_duration_ms": durations,
        "model_versions": versions,
        "categorization": {
            "rows": int(rows),
            "auto_categorized": int(auto),
            "sent_to_review": int(review),
            "auto_rate": round(int(auto) / int(rows), 4) if rows else None,
        },
        "forecast_method_selected": methods,
    }


def main() -> None:
    from backend.core.database import SessionLocal

    with SessionLocal() as db:
        print(json.dumps(build_ops_report(db), indent=2, default=str))


if __name__ == "__main__":
    main()
