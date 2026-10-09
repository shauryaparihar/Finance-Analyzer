"""
FastAPI API routes for the finance analyzer.

NOTE: until authentication is added (next phase), all uploads belong to one built-in demo user.
"""
import hashlib
import io
import traceback
import uuid
from typing import List

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from backend.api.schemas import UploadInfo, UploadResponse
from backend.core import repository as repo
from backend.core.database import SessionLocal, get_db
from backend.ml.pipeline import run_full_pipeline
from backend.utils.amounts import AmountConventionError, apply_amount_convention

router = APIRouter(prefix="/api", tags=["finance"])

DEMO_USER_EMAIL = "demo@finsight.local"
UNUSABLE_PASSWORD_HASH = "!"  # never matches a real password hash, so this user cannot log in


def get_current_user_id(db: Session = Depends(get_db)) -> uuid.UUID:
    """Temporary stand-in for authentication: always the built-in demo user."""
    user = repo.get_user_by_email(db, DEMO_USER_EMAIL)
    if user is None:
        user = repo.create_user(db, DEMO_USER_EMAIL, UNUSABLE_PASSWORD_HASH)
    return user.id


def _run_pipeline_background(user_id: uuid.UUID, upload_id: uuid.UUID, df: pd.DataFrame):
    """Run the ML pipeline in the background."""
    db = SessionLocal()
    try:
        results = run_full_pipeline(df)

        processed_df = results.pop("processed_df", df)
        repo.store_transactions(db, user_id, upload_id, processed_df)

        for module_name, module_data in results.get("modules", {}).items():
            repo.upsert_analysis_result(db, user_id, upload_id, module_name, module_data)

        if results.get("errors"):
            repo.upsert_analysis_result(db, user_id, upload_id, "errors", {"errors": results["errors"]})

        status = "failed" if results.get("status") == "failed" else "completed"
        repo.update_upload_status(db, user_id, upload_id, status)
        print(f"Pipeline {status} for upload {upload_id}")
    except Exception as e:
        traceback.print_exc()
        db.rollback()
        repo.update_upload_status(db, user_id, upload_id, "failed", error_summary="Analysis failed")
        repo.upsert_analysis_result(db, user_id, upload_id, "errors", {"errors": [str(e)]})
    finally:
        db.close()


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    amount_convention: str = Query("auto", description="auto | expenses_positive | expenses_negative"),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Upload a CSV file and trigger the ML pipeline."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    df.columns = df.columns.str.lower().str.strip()
    required_cols = {"date", "amount"}
    if not required_cols.issubset(set(df.columns)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {sorted(required_cols)}. Found: {list(df.columns)}.",
        )

    try:
        df, resolved_convention = apply_amount_convention(df, amount_convention)
    except AmountConventionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upload = repo.create_upload(
        db, user_id, file.filename, hashlib.sha256(contents).hexdigest(), len(df)
    )
    repo.update_upload_status(db, user_id, upload.id, "processing")

    background_tasks.add_task(_run_pipeline_background, user_id, upload.id, df)

    return UploadResponse(
        upload_id=str(upload.id),
        filename=file.filename,
        num_rows=len(df),
        status="processing",
        amount_convention=resolved_convention,
        message="File uploaded successfully. Pipeline is running in the background.",
    )


@router.get("/uploads", response_model=List[UploadInfo])
async def list_uploads(db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    """List the current user's uploads."""
    return [
        UploadInfo(
            id=str(u.id),
            filename=u.original_filename,
            upload_date=u.created_at.isoformat() if u.created_at else "",
            num_rows=u.row_count,
            status=u.status,
        )
        for u in repo.list_uploads(db, user_id)
    ]


@router.get("/status/{upload_id}")
async def get_upload_status(
    upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)
):
    upload = repo.get_upload(db, user_id, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {"upload_id": str(upload_id), "status": upload.status}


@router.get("/results/{upload_id}/{result_type}")
async def get_results(
    upload_id: uuid.UUID,
    result_type: str,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    result = repo.get_analysis_result(db, user_id, upload_id, result_type)
    if result is None:
        # Same answer whether the upload is missing, belongs to someone else, or has no such result.
        raise HTTPException(status_code=404, detail=f"No {result_type} results found")
    return {"result_type": result_type, "data": result}


@router.get("/transactions/{upload_id}")
async def get_upload_transactions(
    upload_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    if repo.get_upload(db, user_id, upload_id) is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    transactions = repo.get_transactions(db, user_id, upload_id, limit=limit, offset=offset)
    return {
        "upload_id": str(upload_id),
        "count": len(transactions),
        "transactions": [
            {
                "id": t.id,
                "date": t.transaction_date.isoformat() if t.transaction_date else None,
                "amount": float(t.amount),
                "category": t.confirmed_category or t.source_category or t.predicted_category or "Uncategorized",
                "description": t.description,
                "predicted_category": t.predicted_category,
                "anomaly_score": t.anomaly_score,
                "anomaly_rank": t.anomaly_rank,
            }
            for t in transactions
        ],
    }


@router.delete("/uploads/{upload_id}", status_code=204)
async def delete_upload(
    upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)
):
    if not repo.delete_upload(db, user_id, upload_id):
        raise HTTPException(status_code=404, detail="Upload not found")


@router.get("/summary/{upload_id}")
async def get_summary(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return await get_results(upload_id, "summary", db, user_id)


@router.get("/predictions/{upload_id}")
async def get_predictions(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return await get_results(upload_id, "prediction", db, user_id)


@router.get("/anomalies/{upload_id}")
async def get_anomalies(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return await get_results(upload_id, "anomaly", db, user_id)


@router.get("/segments/{upload_id}")
async def get_segments(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return await get_results(upload_id, "segmentation", db, user_id)
