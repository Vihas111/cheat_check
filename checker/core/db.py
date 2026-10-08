"""SQLAlchemy models and session helpers (schema from plan.md §5, plus grades)."""

from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from checker.config import get_settings


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    max_score: Mapped[float] = mapped_column(Float, default=100)
    # [{"name": "Part A", "points": 10}, ...]; empty = one overall score out of max_score
    rubric_json: Mapped[list | None] = mapped_column(JSON)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)


class Submission(Base):
    __tablename__ = "submissions"
    # Same bytes under another filename (= another student) is a new submission: exact copies must be flagged.
    __table_args__ = (UniqueConstraint("assignment_id", "sha256", "filename"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    student_pk: Mapped[int | None] = mapped_column(ForeignKey("students.id"))
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_meta_json: Mapped[dict | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    pipeline_version: Mapped[int] = mapped_column(Integer, default=0)
    # queued | processing | done | failed
    status: Mapped[str] = mapped_column(String, default="queued")
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    # scores, coverage_by_source, tier, reasons, thresholds snapshot
    report_json: Mapped[dict | None] = mapped_column(JSON)

    assignment: Mapped[Assignment] = relationship()
    student: Mapped[Student | None] = relationship()
    items: Mapped[list["Item"]] = relationship(back_populates="submission", cascade="all, delete-orphan")


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    idx: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)  # image | page_render | text_block
    source: Mapped[str] = mapped_column(String)  # embedded | render_crop | render | text_layer
    is_content: Mapped[bool] = mapped_column(Boolean, default=True)  # counts toward coverage
    bbox: Mapped[list | None] = mapped_column(JSON)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String, index=True)  # decoded pixels
    raw_sha256: Mapped[str | None] = mapped_column(String)  # encoded bytes as stored in the PDF
    phash: Mapped[bytes | None] = mapped_column(LargeBinary)
    dhash: Mapped[bytes | None] = mapped_column(LargeBinary)
    whash: Mapped[bytes | None] = mapped_column(LargeBinary)
    hash_variants_json: Mapped[dict | None] = mapped_column(JSON)
    sscd_vec: Mapped[bytes | None] = mapped_column(LargeBinary)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    norm_text: Mapped[str | None] = mapped_column(Text)
    ocr_conf: Mapped[float | None] = mapped_column(Float)
    ocr_words_json: Mapped[list | None] = mapped_column(JSON)
    thumb_path: Mapped[str | None] = mapped_column(String)
    # ignored regions found in this image, as [x0, y0, x1, y1] fractions of its width and height
    masks_json: Mapped[list | None] = mapped_column(JSON(none_as_null=True))

    submission: Mapped[Submission] = relationship(back_populates="items")


class Shingle(Base):
    __tablename__ = "shingles"
    id: Mapped[int] = mapped_column(primary_key=True)
    hash: Mapped[int] = mapped_column(Integer)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String, default="word")  # word | line | code
    __table_args__ = (Index("ix_shingles_hash", "hash"),)


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    raw: Mapped[str] = mapped_column(String)
    normalized: Mapped[str] = mapped_column(String, index=True)


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    other_submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    other_item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)  # image_hash | image_feature | ocr_text | code_structure
    score: Mapped[float] = mapped_column(Float)
    detail_json: Mapped[dict | None] = mapped_column(JSON)


class Flag(Base):
    __tablename__ = "flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)  # info | low | medium | high
    evidence_json: Mapped[dict | None] = mapped_column(JSON)


class Whitelist(Base):
    __tablename__ = "whitelist"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # image | shingle | entity
    fingerprint: Mapped[str] = mapped_column(String, index=True)
    scope: Mapped[str | None] = mapped_column(String)  # assignment name, or None = global
    reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String)  # unreviewed | reviewed | false_positive | confirmed
    note: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    # the app's suggestion ({tier, flags}) the reviewer saw; stronger new evidence reopens verification
    suggestion_json: Mapped[dict | None] = mapped_column(JSON)


class Mark(Base):
    """The grader's marks for one submission. Only a person enters or releases these."""
    __tablename__ = "marks"
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True)
    scores_json: Mapped[dict | None] = mapped_column(JSON)  # criterion name -> points
    total: Mapped[float | None] = mapped_column(Float)
    feedback: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | released
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String, default="queued")  # queued | processing | done | failed
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Grade(Base):
    __tablename__ = "grades"
    student_id: Mapped[str] = mapped_column(String, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float)


_engine = None
_Session = None


def init_db(url: str | None = None):
    global _engine, _Session
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(url or s.db_url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(_engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    Base.metadata.create_all(_engine)
    with _engine.begin() as conn:  # ponytail: hand migration for added columns; Alembic if more follow
        for table, col in (("reviews", "suggestion_json"), ("assignments", "rubric_json"), ("items", "masks_json")):
            if col not in [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")]:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} JSON")
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope():
    if _Session is None:
        init_db()
    session = _Session()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
