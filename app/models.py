"""Tables: companions (users), lesson views, quiz attempts, attempt resets."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    city: Mapped[str] = mapped_column(String(60), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class LessonView(Base):
    """A companion opened a lesson. All lessons must be viewed before the module quiz unlocks."""

    __tablename__ = "lesson_views"
    __table_args__ = (UniqueConstraint("user_id", "module_code", "lesson_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    module_code: Mapped[str] = mapped_column(String(20))
    lesson_index: Mapped[int] = mapped_column(Integer)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class QuizAttempt(Base):
    """One quiz attempt. Questions are fixed when the attempt starts, graded on the server."""

    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    module_code: Mapped[str] = mapped_column(String(20), index=True)
    question_ids: Mapped[list] = mapped_column(JSON)
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Attempts made before an admin reset don't count toward the attempt limit.
    counted: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OfflineStep(Base):
    """An offline step (practice day, shadow visit…) a coordinator has marked done for a companion."""

    __tablename__ = "offline_steps"
    __table_args__ = (UniqueConstraint("user_id", "step_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    step_code: Mapped[str] = mapped_column(String(40))
    marked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    done_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Certificate(Base):
    """Issued once a companion passes every online module and every offline step."""

    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
