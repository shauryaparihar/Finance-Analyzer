"""
Admin area: who has an account and how the service is doing. Only aggregates and account details are shown.
An admin can NOT read anyone's transactions or results: those endpoints still filter by the owner's user id.
"""
import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import get_admin_user
from backend.api.errors import AppError
from backend.api.schemas import AdminOverview, AdminUserOut, AdminUserUpdate
from backend.core import repository as repo
from backend.core.database import get_db
from backend.core.logging import log_event
from backend.core.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("finsight.admin")


@router.get("/overview", response_model=AdminOverview)
def overview(db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    return AdminOverview(
        **repo.admin_overview(db),
        note="Counts only. Administrators cannot open other people's transactions or results.",
    )


@router.get("/users", response_model=list[AdminUserOut])
def users(db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    return repo.admin_list_users(db)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: uuid.UUID, body: AdminUserUpdate, db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    """Disable or re-enable an account. A disabled account cannot log in or use an existing session."""
    target = repo.get_user(db, user_id)
    if target is None:
        raise AppError(404, "NOT_FOUND", "User not found.")
    if target.id == admin.id:
        raise AppError(409, "CANNOT_CHANGE_SELF", "You cannot disable your own account.")
    if target.role == "admin":
        raise AppError(409, "CANNOT_CHANGE_ADMIN", "Administrator accounts cannot be disabled here.")
    updated = repo.set_user_active(db, user_id, body.is_active)
    log_event(logger, logging.INFO, "admin_set_user_active", admin_id=str(admin.id), target_id=str(user_id), is_active=body.is_active)
    row = next(u for u in repo.admin_list_users(db) if u["id"] == updated.id)
    return row
