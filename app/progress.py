"""Works out each companion's status per module: locked, open, passed or blocked."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .content import MODULES, Module
from .models import LessonView, QuizAttempt

LOCKED, OPEN, PASSED, BLOCKED = "locked", "open", "passed", "blocked"


@dataclass
class ModuleStatus:
    module: Module
    state: str
    lessons_viewed: int
    best_score: int | None  # best percentage
    attempts_used: int  # counted, submitted attempts
    attempts_total: int  # all submitted attempts, including ones before a reset

    @property
    def lessons_done(self) -> bool:
        return self.lessons_viewed >= len(self.module.lessons)

    @property
    def attempts_left(self) -> int:
        return max(self.module.max_attempts - self.attempts_used, 0)


def percent(score: int, total: int) -> int:
    return round(100 * score / total) if total else 0


def module_statuses(db: Session, user_id: int, unlock_all: bool = False) -> list[ModuleStatus]:
    views = db.execute(
        select(LessonView.module_code, LessonView.lesson_index).where(LessonView.user_id == user_id)
    ).all()
    viewed: dict[str, set[int]] = {}
    for code, index in views:
        viewed.setdefault(code, set()).add(index)

    attempts = db.scalars(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user_id, QuizAttempt.submitted_at.is_not(None)
        )
    ).all()

    statuses = []
    previous_passed = True
    for module in MODULES:
        mine = [a for a in attempts if a.module_code == module.code]
        passed = any(a.passed for a in mine)
        used = sum(1 for a in mine if a.counted)
        best = max((percent(a.score, a.total) for a in mine), default=None)
        lessons_viewed = len(
            {i for i in viewed.get(module.code, set()) if i < len(module.lessons)}
        )

        if passed:
            state = PASSED
        elif not previous_passed and not unlock_all:
            state = LOCKED
        elif used >= module.max_attempts:
            state = BLOCKED
        else:
            state = OPEN

        statuses.append(
            ModuleStatus(module, state, lessons_viewed, best, used, len(mine))
        )
        previous_passed = passed
    return statuses


# ---------- offline steps and certificate ----------

import secrets  # noqa: E402

from .content import OFFLINE_STEPS  # noqa: E402
from .models import Certificate, OfflineStep  # noqa: E402


def offline_done(db: Session, user_id: int) -> dict[str, OfflineStep]:
    rows = db.scalars(select(OfflineStep).where(OfflineStep.user_id == user_id)).all()
    return {r.step_code: r for r in rows}


def get_certificate(db: Session, user_id: int) -> Certificate | None:
    return db.scalar(select(Certificate).where(Certificate.user_id == user_id))


def ensure_certificate(db: Session, user_id: int) -> Certificate | None:
    """Issue the certificate once every online module and every offline step is done."""
    cert = get_certificate(db, user_id)
    if cert:
        return cert
    online_ok = all(s.state == PASSED for s in module_statuses(db, user_id))
    done = offline_done(db, user_id)
    offline_ok = all(step.code in done for step in OFFLINE_STEPS)
    if not (online_ok and offline_ok):
        return None
    while True:
        code = "PA-" + secrets.token_hex(4).upper()
        if not db.scalar(select(Certificate).where(Certificate.code == code)):
            break
    cert = Certificate(user_id=user_id, code=code)
    db.add(cert)
    db.commit()
    return cert
