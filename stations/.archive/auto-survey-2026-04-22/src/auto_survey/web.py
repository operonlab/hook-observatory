"""FastAPI web app for auto-survey — people CRUD + run trigger + status."""

import threading
import time as _time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .db import engine, get_session, init_db
from .models import Base, DailyRun, Person, Question, Submission, Survey

STATIC_DIR = Path(__file__).parent.parent.parent / "static"

app = FastAPI(title="Auto Survey", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _ensure_db():
    init_db()
    Base.metadata.create_all(engine)


def _scheduler_loop():
    """Check every 30s if a 'scheduled' run should start (execution_hour reached)."""
    while True:
        now = datetime.now()
        if now.hour >= settings.execution_hour:
            db = get_session()
            try:
                run = (
                    db.query(DailyRun)
                    .filter(DailyRun.run_date == date.today(), DailyRun.status == "scheduled")
                    .first()
                )
                if run:
                    run.status = "running"
                    run.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    run_id = str(run.id)
                    attend = run.attend_url
                    quiz = run.quiz_url
                    threading.Thread(
                        target=_execute_pipeline_bg,
                        args=(run_id, attend, quiz),
                        daemon=True,
                    ).start()
            except Exception:
                pass
            finally:
                db.close()
        _time.sleep(30)


@app.on_event("startup")
def startup():
    _ensure_db()
    threading.Thread(target=_scheduler_loop, daemon=True).start()


# ── Schemas ──────────────────────────────────────────────


class PersonCreate(BaseModel):
    name: str
    email: str
    company: str
    active: bool = True


class PersonUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None
    active: bool | None = None


class RunRequest(BaseModel):
    attend_url: str | None = None
    quiz_url: str | None = None


class PersonOut(BaseModel):
    id: str
    name: str
    email: str
    company: str
    active: bool
    created_at: str


class DailyRunOut(BaseModel):
    id: str
    run_date: str
    attend_url: str | None
    quiz_url: str | None
    status: str
    result_summary: str | None
    created_at: str


class SubmissionOut(BaseModel):
    id: str
    person_name: str
    survey_title: str
    survey_type: str
    status: str
    score: int | None
    answers_snapshot: dict | None = None
    submitted_at: str


# ── People API ───────────────────────────────────────────


@app.get("/api/people", response_model=list[PersonOut])
def list_people():
    db = get_session()
    try:
        people = db.query(Person).order_by(Person.name).all()
        return [_person_out(p) for p in people]
    finally:
        db.close()


@app.post("/api/people", response_model=PersonOut, status_code=201)
def create_person(data: PersonCreate):
    db = get_session()
    try:
        existing = db.query(Person).filter(Person.email == data.email).first()
        if existing:
            raise HTTPException(400, f"Email already exists: {data.email}")
        person = Person(name=data.name, email=data.email, company=data.company, active=data.active)
        db.add(person)
        db.commit()
        db.refresh(person)
        return _person_out(person)
    finally:
        db.close()


@app.put("/api/people/{person_id}", response_model=PersonOut)
def update_person(person_id: str, data: PersonUpdate):
    db = get_session()
    try:
        person = db.query(Person).filter(Person.id == uuid.UUID(person_id)).first()
        if not person:
            raise HTTPException(404, "Person not found")
        if data.name is not None:
            person.name = data.name
        if data.email is not None:
            person.email = data.email
        if data.company is not None:
            person.company = data.company
        if data.active is not None:
            person.active = data.active
        db.commit()
        db.refresh(person)
        return _person_out(person)
    finally:
        db.close()


@app.delete("/api/people/{person_id}")
def delete_person(person_id: str):
    db = get_session()
    try:
        person = db.query(Person).filter(Person.id == uuid.UUID(person_id)).first()
        if not person:
            raise HTTPException(404, "Person not found")
        db.delete(person)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Run API ──────────────────────────────────────────────


@app.get("/api/runs/today", response_model=DailyRunOut | None)
def get_today_run():
    db = get_session()
    try:
        run = db.query(DailyRun).filter(DailyRun.run_date == date.today()).first()
        return _run_out(run) if run else None
    finally:
        db.close()


@app.get("/api/runs", response_model=list[DailyRunOut])
def list_runs():
    db = get_session()
    try:
        runs = db.query(DailyRun).order_by(DailyRun.run_date.desc()).limit(20).all()
        return [_run_out(r) for r in runs]
    finally:
        db.close()


@app.post("/api/runs", response_model=DailyRunOut, status_code=201)
def create_run(data: RunRequest):
    if not data.attend_url and not data.quiz_url:
        raise HTTPException(400, "Provide at least one URL")

    db = get_session()
    try:
        today = date.today()
        existing = db.query(DailyRun).filter(DailyRun.run_date == today).first()
        if existing and existing.status in ("running", "completed", "scheduled"):
            raise HTTPException(409, f"Today's run already {existing.status}")

        # Time gate: before execution_hour → schedule, after → run immediately
        now = datetime.now()
        new_status = "scheduled" if now.hour < settings.execution_hour else "running"

        if existing:
            existing.attend_url = data.attend_url
            existing.quiz_url = data.quiz_url
            existing.status = new_status
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
            run = existing
        else:
            run = DailyRun(
                run_date=today,
                attend_url=data.attend_url,
                quiz_url=data.quiz_url,
                status=new_status,
            )
            db.add(run)
            db.commit()
            db.refresh(run)

        # Only execute immediately if past execution_hour
        if new_status == "running":
            run_id = str(run.id)
            attend = data.attend_url
            quiz = data.quiz_url
            threading.Thread(
                target=_execute_pipeline_bg,
                args=(run_id, attend, quiz),
                daemon=True,
            ).start()

        return _run_out(run)
    finally:
        db.close()


def _execute_pipeline_bg(run_id: str, attend_url: str | None, quiz_url: str | None):
    """Run the survey pipeline in background, update DailyRun status."""
    from .orchestrator import run_attendance, run_quiz
    from .notify import send_bark

    db = get_session()
    try:
        results = []
        if attend_url:
            try:
                run_attendance(attend_url)
                results.append("attendance: OK")
            except Exception as e:
                results.append(f"attendance: FAILED ({e})")

        if quiz_url:
            try:
                run_quiz(quiz_url)
                results.append("quiz: OK")
            except Exception as e:
                results.append(f"quiz: FAILED ({e})")

        run = db.query(DailyRun).filter(DailyRun.id == uuid.UUID(run_id)).first()
        if run:
            summary = " | ".join(results)
            has_fail = any("FAILED" in r for r in results)
            run.status = "failed" if has_fail else "completed"
            run.result_summary = summary
            run.updated_at = datetime.now(timezone.utc)
            db.commit()

        # Bark notification
        status_emoji = "!" if has_fail else "OK"
        send_bark("Auto Survey", f"{status_emoji} {' | '.join(results)}")
    except Exception as e:
        run = db.query(DailyRun).filter(DailyRun.id == uuid.UUID(run_id)).first()
        if run:
            run.status = "failed"
            run.result_summary = str(e)
            run.updated_at = datetime.now(timezone.utc)
            db.commit()
        send_bark("Auto Survey", f"Pipeline error: {e}")
    finally:
        db.close()


# ── SSE Stream API ──────────────────────────────────────


def _build_day_data(db, run) -> dict:
    """Build the same payload as /api/day/{date} for SSE streaming."""
    from sqlalchemy import func as _func

    target = run.run_date
    subs = (
        db.query(Submission)
        .join(Person)
        .filter(_func.date(Submission.submitted_at) == target)
        .order_by(Person.name)
        .all()
    )
    survey_ids = {s.survey_id for s in subs}
    questions = []
    if survey_ids:
        questions = (
            db.query(Question)
            .filter(Question.survey_id.in_(survey_ids))
            .order_by(Question.subject_id)
            .all()
        )
    person_map: dict[str, dict] = {}
    for s in subs:
        name = s.person.name if s.person else "?"
        if name not in person_map:
            person_map[name] = {
                "person_name": name,
                "attendance": None,
                "quiz": None,
                "score": None,
                "is_pathfinder": False,
                "answers_snapshot": None,
            }
        entry = person_map[name]
        stype = s.survey.type if s.survey else ""
        if stype == "attendance":
            entry["attendance"] = s.status
        elif stype == "quiz":
            entry["quiz"] = s.status
            entry["score"] = s.score
            if s.is_pathfinder:
                entry["is_pathfinder"] = True
            if s.answers_snapshot:
                entry["answers_snapshot"] = s.answers_snapshot
    return {
        "run": _run_out(run).__dict__ if run else None,
        "submissions": list(person_map.values()),
        "questions": [
            {
                "id": str(q.id),
                "subject_id": q.subject_id,
                "question_text": q.question_text,
                "options": q.options,
                "correct_answer": q.correct_answer,
                "verified": q.verified,
            }
            for q in questions
        ],
    }


@app.get("/api/runs/{run_id}/events")
async def run_events_stream(run_id: str):
    """SSE endpoint — push updates until run completes or fails."""
    import asyncio
    import json

    from starlette.responses import StreamingResponse

    async def event_generator():
        last_snapshot = None
        while True:
            db = get_session()
            try:
                run = db.query(DailyRun).filter(DailyRun.id == uuid.UUID(run_id)).first()
                if not run:
                    yield f"event: error\ndata: {json.dumps({'message': 'Run not found'})}\n\n"
                    return

                data = _build_day_data(db, run)
                snapshot = json.dumps(data, ensure_ascii=False, default=str)

                if snapshot != last_snapshot:
                    yield f"data: {snapshot}\n\n"
                    last_snapshot = snapshot

                if run.status in ("completed", "failed"):
                    yield f"event: done\ndata: {json.dumps({'status': run.status})}\n\n"
                    return
            finally:
                db.close()

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── History API ──────────────────────────────────────────


@app.get("/api/history", response_model=list[SubmissionOut])
def list_history():
    db = get_session()
    try:
        subs = (
            db.query(Submission)
            .join(Survey)
            .join(Person)
            .order_by(Submission.submitted_at.desc())
            .limit(100)
            .all()
        )
        return [_submission_out(s) for s in subs]
    finally:
        db.close()


# ── Frontend ─────────────────────────────────────────────


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/sw.js")
def service_worker():
    return FileResponse(str(STATIC_DIR / "sw.js"), media_type="application/javascript")


# ── Helpers ──────────────────────────────────────────────


def _person_out(p: Person) -> PersonOut:
    return PersonOut(
        id=str(p.id),
        name=p.name,
        email=p.email,
        company=p.company,
        active=p.active,
        created_at=p.created_at.isoformat() if p.created_at else "",
    )


def _run_out(r: DailyRun) -> DailyRunOut:
    return DailyRunOut(
        id=str(r.id),
        run_date=r.run_date.isoformat(),
        attend_url=r.attend_url,
        quiz_url=r.quiz_url,
        status=r.status,
        result_summary=r.result_summary,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


def _submission_out(s: Submission) -> SubmissionOut:
    return SubmissionOut(
        id=str(s.id),
        person_name=s.person.name if s.person else "?",
        survey_title=(s.survey.title or s.survey.url)[:40] if s.survey else "?",
        survey_type=s.survey.type if s.survey else "?",
        status=s.status,
        score=s.score,
        answers_snapshot=s.answers_snapshot,
        submitted_at=s.submitted_at.isoformat() if s.submitted_at else "",
    )


# ── Calendar API ────────────────────────────────────────


@app.get("/api/calendar")
def get_calendar(year: int, month: int):
    """Return run status for each day in the given month."""

    db = get_session()
    try:
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        runs = db.query(DailyRun).filter(DailyRun.run_date >= start, DailyRun.run_date < end).all()
        return [{"date": r.run_date.isoformat(), "status": r.status} for r in runs]
    finally:
        db.close()


@app.get("/api/day/{run_date}")
def get_day_detail(run_date: str):
    """Return run info + submissions + questions for a specific date."""
    from sqlalchemy import func as _func  # noqa: F811

    db = get_session()
    try:
        try:
            target = date.fromisoformat(run_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

        run = db.query(DailyRun).filter(DailyRun.run_date == target).first()

        # Get submissions for this date
        subs = (
            db.query(Submission)
            .join(Person)
            .filter(_func.date(Submission.submitted_at) == target)
            .order_by(Person.name)
            .all()
        )

        # Get questions for related surveys
        survey_ids = {s.survey_id for s in subs}
        questions = []
        if survey_ids:
            questions = (
                db.query(Question)
                .filter(Question.survey_id.in_(survey_ids))
                .order_by(Question.subject_id)
                .all()
            )

        # Group submissions by person (one row per person)
        person_map: dict[str, dict] = {}
        for s in subs:
            name = s.person.name if s.person else "?"
            if name not in person_map:
                person_map[name] = {
                    "person_name": name,
                    "attendance": None,
                    "quiz": None,
                    "score": None,
                    "is_pathfinder": False,
                    "answers_snapshot": None,
                }
            entry = person_map[name]
            stype = s.survey.type if s.survey else ""
            if stype == "attendance":
                entry["attendance"] = s.status
            elif stype == "quiz":
                entry["quiz"] = s.status
                entry["score"] = s.score
                if s.is_pathfinder:
                    entry["is_pathfinder"] = True
                if s.answers_snapshot:
                    entry["answers_snapshot"] = s.answers_snapshot

        return {
            "run": _run_out(run) if run else None,
            "submissions": list(person_map.values()),
            "questions": [
                {
                    "id": str(q.id),
                    "subject_id": q.subject_id,
                    "question_text": q.question_text,
                    "options": q.options,
                    "correct_answer": q.correct_answer,
                    "verified": q.verified,
                }
                for q in questions
            ],
        }
    finally:
        db.close()
