"""PeakAge Companion Academy — online LMS.

Companions sign up, go through modules in order, and take a quiz at the end of each.
Admins (phone numbers listed in ADMIN_PHONES) see everyone's progress and can reset attempts.
"""
import csv
import io
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .content import MODULE_BY_CODE, MODULES, OFFLINE_STEP_BY_CODE, OFFLINE_STEPS
from .db import Base, engine, get_db
from .models import Certificate, LessonView, OfflineStep, QuizAttempt, User
from .progress import (
    BLOCKED, LOCKED, OPEN, PASSED, ensure_certificate, get_certificate, module_statuses, offline_done, percent,
)
from .security import hash_password, verify_password

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
ADMIN_PHONES = {p for p in re.split(r"[,\s]+", os.environ.get("ADMIN_PHONES", "")) if p}
REGISTRATION_CODE = os.environ.get("REGISTRATION_CODE", "").strip()
HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "false").lower() == "true"

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PeakAge Companion Academy", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=HTTPS_ONLY,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------- helpers ----------

def normalise_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits if len(digits) == 10 else None


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def render(request: Request, name: str, user: User | None = None, **context) -> HTMLResponse:
    messages = request.session.pop("flash", [])
    return templates.TemplateResponse(
        request, name, {"user": user, "messages": messages, **context}
    )


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return redirect("/login")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is None:
        request.session.pop("user_id", None)
        raise LoginRequired()
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


def get_module_or_404(code: str):
    module = MODULE_BY_CODE.get(code)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return module


def status_for(db: Session, user: User, code: str):
    for status in module_statuses(db, user.id, unlock_all=user.is_admin):
        if status.module.code == code:
            return status
    raise HTTPException(status_code=404, detail="Module not found")


def shuffled_options(attempt_id: int, question) -> list[tuple[int, str]]:
    """Options in a random order that stays the same for this attempt (so a reload doesn't reshuffle)."""
    order = list(range(len(question.options)))
    random.Random(f"{attempt_id}:{question.id}").shuffle(order)
    return [(i, question.options[i]) for i in order]


# ---------- auth ----------

@app.get("/")
def home(request: Request):
    return redirect("/dashboard" if request.session.get("user_id") else "/login")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return render(request, "register.html", needs_code=bool(REGISTRATION_CODE), form={})


@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    city: str = Form(""),
    password: str = Form(...),
    confirm: str = Form(...),
    code: str = Form(""),
    db: Session = Depends(get_db),
):
    form = {"name": name, "phone": phone, "city": city}
    errors = []
    clean_phone = normalise_phone(phone)
    if not name.strip():
        errors.append("Please enter your name.")
    if clean_phone is None:
        errors.append("Please enter a valid 10-digit mobile number.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    if password != confirm:
        errors.append("The two passwords don't match.")
    if REGISTRATION_CODE and code.strip() != REGISTRATION_CODE:
        errors.append("Wrong registration code. Ask your PeakAge coordinator for it.")
    if clean_phone and db.scalar(select(User).where(User.phone == clean_phone)):
        errors.append("This number is already registered. Please log in.")
    if errors:
        for e in errors:
            flash(request, e, "error")
        return render(request, "register.html", needs_code=bool(REGISTRATION_CODE), form=form)

    user = User(
        name=name.strip(),
        phone=clean_phone,
        city=city.strip(),
        password_hash=hash_password(password),
        is_admin=clean_phone in ADMIN_PHONES,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, "This number is already registered. Please log in.", "error")
        return redirect("/login")
    request.session["user_id"] = user.id
    flash(request, f"Welcome to PeakAge Companion Academy, {user.name}!", "success")
    return redirect("/dashboard")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "login.html")


@app.post("/login")
def login(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    clean_phone = normalise_phone(phone)
    user = db.scalar(select(User).where(User.phone == clean_phone)) if clean_phone else None
    if user is None or not verify_password(password, user.password_hash):
        flash(request, "Wrong mobile number or password.", "error")
        return redirect("/login")
    should_be_admin = user.phone in ADMIN_PHONES
    if user.is_admin != should_be_admin:
        user.is_admin = should_be_admin
        db.commit()
    request.session["user_id"] = user.id
    return redirect("/admin" if user.is_admin else "/dashboard")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


# ---------- companion pages ----------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    statuses = module_statuses(db, user.id, unlock_all=user.is_admin)
    passed = sum(1 for s in statuses if s.state == PASSED)
    current = next((s for s in statuses if s.state in (OPEN, BLOCKED)), None)
    return render(
        request, "dashboard.html", user,
        statuses=statuses, passed=passed, total=len(statuses), current=current,
        offline_steps=OFFLINE_STEPS, offline=offline_done(db, user.id),
        certificate=ensure_certificate(db, user.id),
    )


@app.get("/modules/{code}", response_class=HTMLResponse)
def module_page(code: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_module_or_404(code)
    status = status_for(db, user, code)
    if status.state == LOCKED:
        flash(request, "Finish the previous module first.", "error")
        return redirect("/dashboard")
    viewed = set(
        db.scalars(
            select(LessonView.lesson_index).where(
                LessonView.user_id == user.id, LessonView.module_code == code
            )
        ).all()
    )
    return render(request, "module.html", user, status=status, viewed=viewed)


@app.get("/modules/{code}/lessons/{index}", response_class=HTMLResponse)
def lesson_page(code: str, index: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module = get_module_or_404(code)
    if not 0 <= index < len(module.lessons):
        raise HTTPException(status_code=404, detail="Lesson not found")
    status = status_for(db, user, code)
    if status.state == LOCKED:
        flash(request, "Finish the previous module first.", "error")
        return redirect("/dashboard")
    exists = db.scalar(
        select(LessonView).where(
            LessonView.user_id == user.id,
            LessonView.module_code == code,
            LessonView.lesson_index == index,
        )
    )
    if not exists:
        db.add(LessonView(user_id=user.id, module_code=code, lesson_index=index))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return render(request, "lesson.html", user, module=module, index=index, lesson=module.lessons[index])


@app.get("/modules/{code}/quiz", response_class=HTMLResponse)
def quiz_page(code: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module = get_module_or_404(code)
    status = status_for(db, user, code)
    if status.state == LOCKED:
        flash(request, "Finish the previous module first.", "error")
        return redirect("/dashboard")
    if status.state == PASSED:
        flash(request, "You've already passed this module.", "success")
        return redirect(f"/modules/{code}")
    if status.state == BLOCKED:
        flash(request, "You've used all your attempts. Please call your PeakAge coordinator.", "error")
        return redirect(f"/modules/{code}")
    if not status.lessons_done:
        flash(request, "Open every lesson in this module before taking the quiz.", "error")
        return redirect(f"/modules/{code}")

    # Resume an unfinished attempt (same questions) instead of drawing fresh ones.
    attempt = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.module_code == code,
            QuizAttempt.submitted_at.is_(None),
        )
    )
    if attempt is None or any(qid not in module.question_map for qid in attempt.question_ids):
        if attempt is not None:
            db.delete(attempt)
        ids = random.sample([q.id for q in module.questions], module.questions_per_quiz)
        attempt = QuizAttempt(user_id=user.id, module_code=code, question_ids=ids, total=len(ids))
        db.add(attempt)
        db.commit()

    answered = attempt.answers or {}
    questions = []
    for qid in attempt.question_ids:
        q = module.question_map[qid]
        item = {"q": q, "options": shuffled_options(attempt.id, q), "chosen": answered.get(qid)}
        if qid in answered:
            item["correct"] = answered[qid] == q.answer
        questions.append(item)
    return render(request, "quiz.html", user, module=module, status=status, attempt=attempt, questions=questions)


@app.post("/modules/{code}/quiz", response_class=HTMLResponse)
async def submit_quiz(code: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module = get_module_or_404(code)
    form = await request.form()
    attempt_id = form.get("attempt_id", "")
    attempt = db.get(QuizAttempt, int(attempt_id)) if str(attempt_id).isdigit() else None
    if (
        attempt is None
        or attempt.user_id != user.id
        or attempt.module_code != code
        or attempt.submitted_at is not None
    ):
        flash(request, "That quiz was already submitted or has expired. Please start again.", "error")
        return redirect(f"/modules/{code}")

    stored = dict(attempt.answers or {})
    answers, results, score = {}, [], 0
    for qid in attempt.question_ids:
        question = module.question_map.get(qid)
        if question is None:
            continue
        if qid in stored:
            chosen = stored[qid]  # answered one by one in the interactive quiz; locked
        else:
            raw = form.get(f"q_{qid}")
            chosen = int(raw) if raw is not None and str(raw).isdigit() else None
        correct = chosen == question.answer
        score += int(correct)
        answers[qid] = chosen
        results.append({"q": question, "chosen": chosen, "correct": correct})

    pct = percent(score, attempt.total)
    attempt.answers = answers
    attempt.score = score
    attempt.passed = pct >= module.pass_percent
    attempt.submitted_at = datetime.now(timezone.utc)
    db.commit()

    status = status_for(db, user, code)
    next_module = next((m for m in MODULES if m.order > module.order), None)
    all_online_done = all(st.state == PASSED for st in module_statuses(db, user.id))
    ensure_certificate(db, user.id)
    return render(
        request, "result.html", user,
        module=module, attempt=attempt, pct=pct, results=results, status=status,
        next_module=next_module, all_online_done=all_online_done,
    )


@app.post("/api/attempts/{attempt_id}/answer")
async def answer_question(attempt_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Interactive quiz: lock in one answer and get instant feedback. The first answer is final."""
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id or attempt.submitted_at is not None:
        return JSONResponse({"error": "This quiz attempt is no longer active."}, status_code=409)
    module = MODULE_BY_CODE.get(attempt.module_code)
    try:
        body = await request.json()
        qid, choice = str(body["question_id"]), int(body["choice"])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"error": "Bad request"}, status_code=400)
    question = module.question_map.get(qid) if module else None
    if question is None or qid not in attempt.question_ids or not 0 <= choice < len(question.options):
        return JSONResponse({"error": "Unknown question or option"}, status_code=400)

    answers = dict(attempt.answers or {})
    if qid not in answers:
        answers[qid] = choice
        attempt.answers = answers  # reassign so the JSON column is saved
        db.commit()
    locked = answers[qid]
    return {
        "question_id": qid,
        "choice": locked,
        "correct": locked == question.answer,
        "correct_choice": question.answer,
        "explanation": question.explanation,
        "answered": len(answers),
        "total": attempt.total,
        "score": sum(1 for k, v in answers.items() if module.question_map[k].answer == v),
    }


@app.get("/certificate", response_class=HTMLResponse)
def my_certificate(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cert = ensure_certificate(db, user.id)
    if cert is None:
        flash(request, "Your certificate unlocks once every online module and offline step is complete.", "info")
        return redirect("/dashboard")
    return render(request, "certificate.html", user, cert=cert, holder=user, verify_url=str(request.url_for("verify", code=cert.code)))


@app.get("/verify/{code}", response_class=HTMLResponse, name="verify")
def verify_certificate(code: str, request: Request, db: Session = Depends(get_db)):
    cert = db.scalar(select(Certificate).where(Certificate.code == code.upper()))
    holder = db.get(User, cert.user_id) if cert else None
    user_id = request.session.get("user_id")
    viewer = db.get(User, user_id) if user_id else None
    return render(request, "verify.html", viewer, cert=cert, holder=holder, code=code.upper())


# ---------- admin ----------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, city: str = "", user: User = Depends(admin_user), db: Session = Depends(get_db)):
    query = select(User).where(User.is_admin.is_(False)).order_by(User.created_at.desc())
    if city:
        query = query.where(User.city.ilike(city))
    companions = db.scalars(query).all()
    rows = []
    for c in companions:
        statuses = module_statuses(db, c.id)
        rows.append({
            "user": c,
            "statuses": statuses,
            "offline": len(offline_done(db, c.id)),
            "certificate": get_certificate(db, c.id),
            "passed": sum(1 for s in statuses if s.state == PASSED),
            "blocked": sum(1 for s in statuses if s.state == BLOCKED),
        })
    cities = sorted({c for c in db.scalars(select(User.city).where(User.is_admin.is_(False))).all() if c})
    return render(
        request, "admin.html", user,
        rows=rows, modules=MODULES, cities=cities, city=city, offline_total=len(OFFLINE_STEPS),
        fully_done=sum(1 for r in rows if r["passed"] == len(MODULES)),
        need_help=sum(1 for r in rows if r["blocked"]),
    )


@app.get("/admin/companions/{companion_id}", response_class=HTMLResponse)
def admin_companion(companion_id: int, request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    companion = db.get(User, companion_id)
    if companion is None:
        raise HTTPException(status_code=404, detail="Companion not found")
    attempts = db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == companion.id, QuizAttempt.submitted_at.is_not(None))
        .order_by(QuizAttempt.submitted_at.desc())
    ).all()
    return render(
        request, "admin_companion.html", user,
        companion=companion, statuses=module_statuses(db, companion.id),
        attempts=attempts, module_by_code=MODULE_BY_CODE, percent=percent,
        offline_steps=OFFLINE_STEPS, offline=offline_done(db, companion.id),
        certificate=get_certificate(db, companion.id),
    )


@app.post("/admin/companions/{companion_id}/offline")
def admin_offline_step(
    companion_id: int,
    request: Request,
    step_code: str = Form(...),
    done: str = Form(...),
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    companion = db.get(User, companion_id)
    step = OFFLINE_STEP_BY_CODE.get(step_code)
    if companion is None or step is None:
        raise HTTPException(status_code=404, detail="Not found")
    existing = db.scalar(
        select(OfflineStep).where(OfflineStep.user_id == companion_id, OfflineStep.step_code == step_code)
    )
    if done == "1" and existing is None:
        db.add(OfflineStep(user_id=companion_id, step_code=step_code, marked_by=user.id))
        db.commit()
        flash(request, f"Marked “{step.title}” done for {companion.name}.", "success")
    elif done == "0" and existing is not None:
        db.delete(existing)
        db.commit()
        flash(request, f"Unmarked “{step.title}” for {companion.name}.", "info")
    cert = ensure_certificate(db, companion_id)
    if cert and done == "1":
        flash(request, f"🎉 {companion.name} is now a certified go-solo companion ({cert.code}).", "success")
    return redirect(f"/admin/companions/{companion_id}")


@app.post("/admin/companions/{companion_id}/reset")
def admin_reset_attempts(
    companion_id: int,
    request: Request,
    module_code: str = Form(...),
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    get_module_or_404(module_code)
    db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.user_id == companion_id, QuizAttempt.module_code == module_code)
        .values(counted=False)
    )
    db.commit()
    flash(request, f"Attempts reset for {module_code}. The companion can take the quiz again.", "success")
    return redirect(f"/admin/companions/{companion_id}")


@app.post("/admin/companions/{companion_id}/password")
def admin_set_password(
    companion_id: int,
    request: Request,
    new_password: str = Form(...),
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    companion = db.get(User, companion_id)
    if companion is None:
        raise HTTPException(status_code=404, detail="Companion not found")
    if len(new_password) < 6:
        flash(request, "Password must be at least 6 characters.", "error")
    else:
        companion.password_hash = hash_password(new_password)
        db.commit()
        flash(request, f"New password set for {companion.name}. Share it with them on call.", "success")
    return redirect(f"/admin/companions/{companion_id}")


@app.get("/admin/export.csv")
def admin_export(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Name", "Phone", "City", "Registered", "Module code", "Module",
        "Status", "Best score %", "Attempts (counted)", "Attempts (all)", "Offline steps done", "Certificate",
    ])
    for c in db.scalars(select(User).where(User.is_admin.is_(False)).order_by(User.name)).all():
        offline_count = f"{len(offline_done(db, c.id))}/{len(OFFLINE_STEPS)}"
        cert = get_certificate(db, c.id)
        for s in module_statuses(db, c.id):
            writer.writerow([
                c.name, c.phone, c.city, c.created_at.date().isoformat(), s.module.code, s.module.title,
                s.state, "" if s.best_score is None else s.best_score, s.attempts_used, s.attempts_total,
                offline_count, cert.code if cert else "",
            ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=peakage-lms-progress.csv"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(
        request, "error.html",
        {"user": None, "messages": [], "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


# Make state names available to templates.
TRACK_ICONS = {
    "Behavioural": "💬", "Technical": "🏥", "Safety": "🛡️",
    "Emergency": "🚨", "Medical": "🩺", "Professionalism": "👔",
}
templates.env.globals.update(
    LOCKED=LOCKED, OPEN=OPEN, PASSED=PASSED, BLOCKED=BLOCKED,
    track_icon=lambda track: TRACK_ICONS.get(track, "📘"),
)
