"""Main orchestrator — coordinates recon, analyze, and fill phases."""

import random
import sys
import time
from pathlib import Path

import click
from sqlalchemy.orm import Session

from .analyzer import analyze_quiz, reanalyze_wrong
from .config import settings
from .db import get_session
from .filler import fill_form
from .models import Person, Submission, Survey
from .pw import cleanup_session, create_session
from .recon import classify_subjects, recon_survey, save_survey

# Wire reactive store
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def _log(msg: str):
    click.echo(f"[auto-survey] {msg}")


def run_attendance(url: str, dry_run: bool = False):
    """Run attendance automation for all active people."""
    db = get_session()
    try:
        _run_pipeline(db, url, survey_type="attendance", dry_run=dry_run)
    finally:
        db.close()


def run_quiz(url: str, dry_run: bool = False):
    """Run quiz automation for all active people."""
    db = get_session()
    try:
        _run_pipeline(db, url, survey_type="quiz", dry_run=dry_run)
    finally:
        db.close()


def _dispatch_store(action_creator, **kwargs):
    """Fire-and-forget store dispatch (sync context)."""
    try:
        from store import survey_store

        survey_store.dispatch_sync(action_creator(**kwargs))
    except Exception:
        pass  # noqa: S110 — store dispatch is best-effort


def _run_pipeline(db: Session, url: str, survey_type: str, dry_run: bool = False):
    from store import SurveyStarted

    people = db.query(Person).filter(Person.active.is_(True)).all()
    if not people:
        _log("No active people found. Import with: auto-survey people import <csv>")
        return

    _log(f"Found {len(people)} active people")
    _dispatch_store(SurveyStarted, survey_type=survey_type, url=url, people_count=len(people))

    # Phase 1: Recon
    _log("Phase 1: Recon — extracting form structure...")
    pw = create_session()
    try:
        structure = recon_survey(pw, url)
        classified = classify_subjects(structure.get("subjects", []))
        survey = save_survey(db, url, survey_type, structure, classified)
        _log(f"Survey: {survey.title} ({survey.type})")

        if classified["questions"]:
            _log(f"  Found {len(classified['questions'])} quiz questions")
        if classified["company"]:
            _log(f"  Company options: {classified['company']['options']}")
    finally:
        pw.close()
        cleanup_session(pw)

    # Phase 2: Analyze (quiz only)
    answers: dict[str, str] = {}
    if survey_type == "quiz" and classified["questions"]:
        _log("Phase 2: Analyze — getting answers from LLM...")
        answers = analyze_quiz(db, survey)
        _log(f"  Got {len(answers)} answers")
        for sid, ans in answers.items():
            _log(f"    {sid}: {ans}")

    if dry_run:
        _log("Dry run — skipping form filling")
        return

    # Phase 3: Fill
    _log("Phase 3: Fill — submitting forms...")
    random.shuffle(people)

    # Pathfinder: randomly selected scout (shuffle already done above)
    if survey_type == "quiz" and answers:
        scout = people[0]
        _log(f"Pathfinder: {scout.name} goes first...")
        _fill_one_person(db, survey, scout, answers)

        # Mark as pathfinder
        sub = (
            db.query(Submission)
            .filter(Submission.survey_id == survey.id, Submission.person_id == scout.id)
            .first()
        )
        if sub:
            sub.is_pathfinder = True
            db.commit()

        if sub and sub.status == "success" and sub.score is not None:
            _log(f"  Pathfinder score: {sub.score}")
            if sub.score < 100:
                _log("  Score < 100 — re-analyzing wrong answers...")
                # We don't know which specific ones are wrong, so re-analyze all
                all_subjects = list(answers.keys())
                new_answers = reanalyze_wrong(db, survey, all_subjects)
                answers.update(new_answers)
                _log(f"  Updated {len(new_answers)} answers")
        elif sub and sub.status == "success" and sub.score is None:
            _log("  Could not extract score — proceeding with current answers")

        remaining = people[1:]
    else:
        remaining = people

    # Fill for remaining people
    for i, person in enumerate(remaining):
        # Check if already submitted
        existing = (
            db.query(Submission)
            .filter(
                Submission.survey_id == survey.id,
                Submission.person_id == person.id,
                Submission.status == "success",
            )
            .first()
        )
        if existing:
            _log(f"  [{i + 1}/{len(remaining)}] {person.name} — already submitted, skipping")
            continue

        # Stagger delay
        if i > 0:
            delay = random.randint(settings.min_delay, settings.max_delay)
            _log(f"  Waiting {delay}s before next submission...")
            time.sleep(delay)

        _log(f"  [{i + 1}/{len(remaining)}] {person.name}...")
        _fill_one_person(db, survey, person, answers if survey_type == "quiz" else None)

        sub = (
            db.query(Submission)
            .filter(Submission.survey_id == survey.id, Submission.person_id == person.id)
            .first()
        )
        if sub:
            status = sub.status
            score_str = f" (score: {sub.score})" if sub.score is not None else ""
            err_str = f" — {sub.error_message}" if sub.error_message else ""
            _log(f"    Result: {status}{score_str}{err_str}")

    # Summary + store dispatch
    subs = db.query(Submission).filter(Submission.survey_id == survey.id).all()
    success = sum(1 for s in subs if s.status == "success")
    from store import SurveyCompleted

    _dispatch_store(
        SurveyCompleted,
        survey_type=survey_type,
        success_count=success,
        total_count=len(subs),
    )
    _print_summary(db, survey)


def _fill_one_person(
    db: Session,
    survey: Survey,
    person: Person,
    answers: dict[str, str] | None,
):
    pw = create_session()
    try:
        fill_form(pw, db, survey, person, answers)
    finally:
        pw.close()
        cleanup_session(pw)


def _print_summary(db: Session, survey: Survey):
    subs = db.query(Submission).filter(Submission.survey_id == survey.id).all()
    total = len(subs)
    success = sum(1 for s in subs if s.status == "success")
    failed = sum(1 for s in subs if s.status == "failed")

    _log("=" * 50)
    _log(f"Summary: {success}/{total} success, {failed} failed")

    if survey.type == "quiz":
        scores = [s.score for s in subs if s.score is not None]
        if scores:
            _log(f"  Avg score: {sum(scores) / len(scores):.1f}")
            _log(f"  Min: {min(scores)}, Max: {max(scores)}")
            passed = sum(1 for s in scores if s >= 60)
            _log(f"  Pass rate (>=60): {passed}/{len(scores)}")
