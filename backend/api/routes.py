"""
FastAPI API routes for the finance analyzer.
"""
import pandas as pd
import io
import traceback
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List

from backend.core.database import (
    get_db, init_db, create_upload, update_upload_status,
    store_transactions, store_pipeline_result, get_upload,
    get_transactions, get_pipeline_result, get_all_uploads,
)
from backend.ml.pipeline import run_full_pipeline
from backend.api.schemas import UploadResponse, TransactionOut, UploadInfo

router = APIRouter(prefix="/api", tags=["finance"])


def _run_pipeline_background(upload_id: int, df: pd.DataFrame):
    """Run the ML pipeline in background."""
    from backend.core.database import SessionLocal

    db = SessionLocal()
    try:
        results = run_full_pipeline(df)

        # Store processed transactions
        processed_df = results.pop("processed_df", df)
        store_transactions(db, upload_id, processed_df)

        # Store each module's results
        for module_name, module_data in results.get("modules", {}).items():
            store_pipeline_result(db, upload_id, module_name, module_data)

        # Store errors if any
        if results.get("errors"):
            store_pipeline_result(db, upload_id, "errors", {"errors": results["errors"]})

        update_upload_status(db, upload_id, "completed")
        print(f"✅ Pipeline completed for upload {upload_id}")

    except Exception as e:
        traceback.print_exc()
        update_upload_status(db, upload_id, "failed")
        store_pipeline_result(db, upload_id, "errors", {"errors": [str(e)]})
    finally:
        db.close()


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a CSV file and trigger the ML pipeline."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    # Clean and check columns
    df.columns = df.columns.str.lower().str.strip()
    available_cols = set(df.columns)
    required_cols = {"date", "amount"}
    
    if not required_cols.issubset(available_cols):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {list(required_cols)}. Found: {list(df.columns)}. Make sure headers match exactly."
        )

    # Create upload record
    upload = create_upload(db, file.filename, len(df))

    # Run pipeline in background
    background_tasks.add_task(_run_pipeline_background, upload.id, df)

    return UploadResponse(
        upload_id=upload.id,
        filename=file.filename,
        num_rows=len(df),
        status="processing",
        message="File uploaded successfully. Pipeline is running in the background.",
    )


@router.get("/uploads", response_model=List[UploadInfo])
async def list_uploads(db: Session = Depends(get_db)):
    """List all uploads."""
    uploads = get_all_uploads(db)
    return [
        UploadInfo(
            id=u.id,
            filename=u.filename,
            upload_date=u.upload_date.isoformat() if u.upload_date else "",
            num_rows=u.num_rows,
            status=u.status,
        )
        for u in uploads
    ]


@router.get("/status/{upload_id}")
async def get_upload_status(upload_id: int, db: Session = Depends(get_db)):
    """Check processing status of an upload."""
    upload = get_upload(db, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {"upload_id": upload_id, "status": upload.status}


@router.get("/results/{upload_id}/{result_type}")
async def get_results(upload_id: int, result_type: str, db: Session = Depends(get_db)):
    """Fetch pipeline results by type."""
    upload = get_upload(db, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    result = get_pipeline_result(db, upload_id, result_type)
    if not result:
        raise HTTPException(status_code=404, detail=f"No {result_type} results found")

    return {"result_type": result_type, "data": result}


@router.get("/transactions/{upload_id}")
async def get_upload_transactions(upload_id: int, db: Session = Depends(get_db)):
    """Fetch processed transactions for an upload."""
    upload = get_upload(db, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    transactions = get_transactions(db, upload_id)
    return {
        "upload_id": upload_id,
        "count": len(transactions),
        "transactions": [
            {
                "id": t.id,
                "date": t.date.isoformat() if t.date else None,
                "amount": t.amount,
                "category": t.category,
                "description": t.description,
                "predicted_category": t.predicted_category,
                "is_anomaly": t.is_anomaly,
                "anomaly_score": t.anomaly_score,
                "cluster_label": t.cluster_label,
            }
            for t in transactions
        ],
    }


@router.get("/summary/{upload_id}")
async def get_summary(upload_id: int, db: Session = Depends(get_db)):
    """Fetch spending summary."""
    return await get_results(upload_id, "summary", db)


@router.get("/predictions/{upload_id}")
async def get_predictions(upload_id: int, db: Session = Depends(get_db)):
    """Fetch expense predictions."""
    return await get_results(upload_id, "prediction", db)


@router.get("/anomalies/{upload_id}")
async def get_anomalies(upload_id: int, db: Session = Depends(get_db)):
    """Fetch anomaly detection results."""
    return await get_results(upload_id, "anomaly", db)


@router.get("/segments/{upload_id}")
async def get_segments(upload_id: int, db: Session = Depends(get_db)):
    """Fetch segmentation results."""
    return await get_results(upload_id, "segmentation", db)
