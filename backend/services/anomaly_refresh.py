"""
Keep the unusual-transaction queue consistent with the user's category corrections.

Each expense is judged against the typical amount for its category, so when a correction moves a transaction to
another category the whole ranking can change (a 1,500 rent payment filed under Groceries is unusual; filed under
Rent it is not). The ranking is therefore recomputed from the stored transactions after such a correction.
Confirm/dismiss decisions are never lost: a transaction that leaves the queue keeps its decision, and gets it back
if it re-enters the queue.
"""
import uuid

from sqlalchemy.orm import Session

from backend.core import repository as repo
from backend.ml.anomaly import MIN_EXPENSES, rank_unusual


def refresh_anomaly_ranking(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> bool:
    """Recompute the review queue for an upload. Returns True if it was recomputed."""
    summary = repo.get_analysis_result(db, user_id, upload_id, "anomaly")
    if not summary or summary.get("status") != "completed":
        return False  # nothing was ranked at upload time (too few expenses, or the step failed)

    frame = repo.transactions_dataframe(db, user_id, upload_id)
    expenses = frame[(frame["amount"] > 0) & frame["date"].notna()].set_index("id")
    if len(expenses) < MIN_EXPENSES:
        return False

    ranked = rank_unusual(expenses)
    repo.update_anomaly_columns(db, user_id, upload_id, ranked)
    summary["flagged"] = int(ranked["anomaly_rank"].notna().sum())
    repo.upsert_analysis_result(db, user_id, upload_id, "anomaly", summary)
    return True
