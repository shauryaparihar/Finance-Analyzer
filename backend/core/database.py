"""
SQLite database connection and ORM models via SQLAlchemy.
"""
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from backend.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    upload_date = Column(DateTime, default=datetime.utcnow)
    num_rows = Column(Integer, default=0)
    status = Column(String(50), default="processing")  # processing, completed, failed

    transactions = relationship("Transaction", back_populates="upload", cascade="all, delete-orphan")
    pipeline_results = relationship("PipelineResult", back_populates="upload", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=False)
    date = Column(DateTime, nullable=True)
    amount = Column(Float, nullable=False)
    category = Column(String(100), nullable=True)
    description = Column(String(500), nullable=True)
    predicted_category = Column(String(100), nullable=True)
    is_anomaly = Column(Boolean, default=False)
    anomaly_score = Column(Float, nullable=True)
    cluster_label = Column(Integer, nullable=True)

    upload = relationship("Upload", back_populates="transactions")


class PipelineResult(Base):
    __tablename__ = "pipeline_results"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=False)
    result_type = Column(String(50), nullable=False)  # categorization, prediction, anomaly, segmentation, summary
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    upload = relationship("Upload", back_populates="pipeline_results")


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Yield a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- CRUD helpers ---

def create_upload(db, filename: str, num_rows: int) -> Upload:
    upload = Upload(filename=filename, num_rows=num_rows)
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def update_upload_status(db, upload_id: int, status: str):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if upload:
        upload.status = status
        db.commit()


def store_transactions(db, upload_id: int, df):
    """Store a DataFrame of transactions into the DB."""
    records = []
    for _, row in df.iterrows():
        txn = Transaction(
            upload_id=upload_id,
            date=row.get("date"),
            amount=row.get("amount"),
            category=row.get("category"),
            description=row.get("description"),
            predicted_category=row.get("predicted_category"),
            is_anomaly=row.get("is_anomaly", False),
            anomaly_score=row.get("anomaly_score"),
            cluster_label=row.get("cluster_label"),
        )
        records.append(txn)
    db.bulk_save_objects(records)
    db.commit()


from backend.utils.helpers import safe_json_serializable

def store_pipeline_result(db, upload_id: int, result_type: str, result_data: dict):
    result = PipelineResult(
        upload_id=upload_id,
        result_type=result_type,
        result_json=json.dumps(safe_json_serializable(result_data), default=str),
    )
    db.add(result)
    db.commit()


def get_upload(db, upload_id: int):
    return db.query(Upload).filter(Upload.id == upload_id).first()


def get_transactions(db, upload_id: int):
    return db.query(Transaction).filter(Transaction.upload_id == upload_id).all()


def get_pipeline_result(db, upload_id: int, result_type: str):
    result = (
        db.query(PipelineResult)
        .filter(PipelineResult.upload_id == upload_id, PipelineResult.result_type == result_type)
        .order_by(PipelineResult.created_at.desc())
        .first()
    )
    if result:
        return json.loads(result.result_json)
    return None


def get_all_uploads(db):
    return db.query(Upload).order_by(Upload.upload_date.desc()).all()
