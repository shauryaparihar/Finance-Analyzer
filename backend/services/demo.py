"""
The read-only demo account: one shared guest user whose analysis of the bundled sample file is created on first use.
The guest can look at every screen but cannot upload, edit or delete (see deps.get_writer_user).
"""
import hashlib
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core import repository as repo
from backend.core.config import BASE_DIR, settings
from backend.core.logging import log_event, request_id_var
from backend.core.models import User
from backend.services.job_input import encode_input
from backend.utils.csv_ingest import validate_and_clean_csv

logger = logging.getLogger("finsight.demo")
DEMO_SAMPLE = BASE_DIR / "data" / "sample_descriptions_only.csv"


def ensure_demo_analysis(db: Session, user: User) -> bool:
    """Queue the sample analysis for the demo user if they have none yet. Returns True if a job was queued."""
    if repo.list_uploads(db, user.id):
        return False
    contents = DEMO_SAMPLE.read_bytes()
    ingest = validate_and_clean_csv(
        contents, DEMO_SAMPLE.name, "auto",
        max_bytes=settings.max_upload_bytes, max_rows=settings.max_upload_rows, max_invalid_share=settings.max_invalid_row_share,
    )
    try:
        repo.enqueue_upload(
            db, user.id, DEMO_SAMPLE.name, hashlib.sha256(contents).hexdigest(), len(ingest.df), ingest.amount_convention,
            encode_input(ingest.df), request_id_var.get(),
        )
    except IntegrityError:  # another guest arrived at the same moment and already queued it
        db.rollback()
        return False
    log_event(logger, logging.INFO, "demo_analysis_queued", user_id=str(user.id), rows=len(ingest.df))
    return True
