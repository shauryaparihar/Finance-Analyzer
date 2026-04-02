import json
import os
import sys
from sqlalchemy.orm import Session

# Add the project root to sys.path
sys.path.append(os.getcwd())

from backend.core.database import SessionLocal, PipelineResult, Upload

def verify_db():
    db = SessionLocal()
    try:
        # Get latest upload
        upload = db.query(Upload).order_by(Upload.upload_date.desc()).first()
        if not upload:
            print("No uploads found in DB.")
            return

        print(f"Checking results for Upload ID: {upload.id} ({upload.filename})")
        print(f"Status: {upload.status}")
        
        # Get summary result
        result = db.query(PipelineResult).filter(
            PipelineResult.upload_id == upload.id,
            PipelineResult.result_type == "summary"
        ).first()
        
        if not result:
            print("❌ No 'summary' result found for this upload.")
            return
            
        data = json.loads(result.result_json)
        print("\n--- Summary JSON Data ---")
        keys = list(data.keys())
        print(f"Available keys: {keys}")
        
        target_keys = ["avg_monthly_spending", "num_anomalies", "category_spending"]
        for tk in target_keys:
            if tk in data:
                val = data[tk]
                if isinstance(val, list):
                    print(f"✅ {tk}: Found (list of {len(val)})")
                else:
                    print(f"✅ {tk}: {val}")
            else:
                print(f"❌ {tk}: MISSING")
                
    finally:
        db.close()

if __name__ == "__main__":
    verify_db()
